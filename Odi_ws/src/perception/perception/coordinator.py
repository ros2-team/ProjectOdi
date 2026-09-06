import math

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from std_msgs.msg import Bool
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

# ▼▼▼▼▼ 여기만 네 환경에 맞게 바꿀 것 ▼▼▼▼▼
# YOLO 가 발행하는 detection 메시지 타입을 import 한다.
from odi_interfaces.msg import DetectedObject
# ▲▲▲▲▲ 패키지명·메시지명이 다르면 위 줄을 고칠 것 ▲▲▲▲▲


class ObserveCoordinator(Node):
    """
    관찰 시퀀스를 혼자 담당하는 노드.

    IDLE ─(detection)─▶ PAUSING ─▶ LOCATING ─▶ NAVIGATING ─▶ CAPTURING ─▶ IDLE

    다른 노드들은 자기 일만 한다:
      YOLO            : bbox 발행만
      object_locator  : 좌표 계산만
      explore         : 탐사만
    순서는 전부 이 노드가 안다.
    """

    def __init__(self):
        super().__init__('observe_coordinator')

        # ============ 토픽 이름 ============
        # ▼ YOLO 가 detection 을 발행하는 토픽 이름으로 바꿀 것
        self.detection_topic = '/yolo/detection'

        # ▼ 아래 3개는 새로 만드는 토픽이라 이름을 네가 정하면 된다
        self.locate_request_topic = '/observe/locate_request'
        self.approach_goal_topic = '/observe/approach_goal'
        self.capture_request_topic = '/observe/capture_request'

        self.explore_resume_topic = '/explore/resume'
        # ==================================

        # ============ 시간 설정 (초) ============
        self.settle_time = 2.0      # 탐사 정지 후 로봇이 멈출 때까지 기다리는 시간
        self.locate_timeout = 5.0   # 좌표가 안 오면 포기
        self.nav_timeout = 120.0    # 이동이 안 끝나면 포기
        self.capture_time = 3.0     # 촬영·전송에 주는 시간
        # =======================================

        self.state = 'IDLE'
        self.state_entered_at = self.get_clock().now()
        self.pending_detection = None
        self.nav_goal_handle = None

        ################################### --- 구독 ---
        # 욜로 데이터 받았다
        self.create_subscription(DetectedObject, self.detection_topic, self.detection_cb, 10)

        # 물체 좌표 데이터 받았다
        self.create_subscription(PoseStamped, self.approach_goal_topic, self.approach_goal_cb, 10)

        ################################### --- 발행 ---
        # 자동 탐사 멈춰/재개해라
        self.resume_pub = self.create_publisher(Bool, self.explore_resume_topic, 10)

        # 욜로 데이터 보낼테니 물체와의 좌표 보내라
        self.locate_req_pub = self.create_publisher(DetectedObject, self.locate_request_topic, 10)

        # 접근 후 2차 사진 찍어라
        self.capture_req_pub = self.create_publisher(Bool, self.capture_request_topic, 10)

        # --- nav2 ---
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        # --- 상태 감시용 타이머 (1초마다) ---
        self.create_timer(1.0, self.watchdog)

        self.get_logger().info('observe_coordinator 시작. 상태=IDLE')

    # ================= 상태 관리 =================

    def set_state(self, new_state):
        self.get_logger().info('상태 전환: %s -> %s' % (self.state, new_state))
        self.state = new_state
        self.state_entered_at = self.get_clock().now()

    def elapsed(self):
        """현재 상태에 들어온 지 몇 초 지났는지"""
        dt = self.get_clock().now() - self.state_entered_at
        return dt.nanoseconds / 1e9

    def finish(self, reason):
        """관찰 시퀀스를 끝내고 탐사를 재개한다. 성공이든 실패든 여기로 온다."""
        self.get_logger().info('관찰 종료 (%s). 탐사 재개.' % reason)
        self.pending_detection = None
        self.nav_goal_handle = None
        self.publish_resume(True)
        self.set_state('IDLE')

    def publish_resume(self, value):
        msg = Bool()
        msg.data = value
        self.resume_pub.publish(msg)
        self.get_logger().info('/explore/resume <- %s' % value)

    # ================= 1. 발견 =================

    def detection_cb(self, msg):
        if self.state != 'IDLE':
            # 관찰 중에 들어온 detection 은 전부 무시한다
            return

        self.get_logger().info('=' * 45)
        self.get_logger().info('[1] 객체 발견. 관찰 시퀀스 시작.')
        self.pending_detection = msg

        self.publish_resume(False)
        self.set_state('PAUSING')

    # ================= 2. 정지 대기 → 좌표 요청 =================

    def request_locate(self):
        self.get_logger().info('[2] 좌표 계산 요청')
        self.locate_req_pub.publish(self.pending_detection)
        self.set_state('LOCATING')

    # ================= 3. 좌표 수신 → nav2 =================

    def approach_goal_cb(self, msg):
        if self.state != 'LOCATING':
            self.get_logger().warn('LOCATING 상태가 아닌데 goal 이 왔다. 무시.')
            return

        self.get_logger().info('[3] goal 수신: (%.2f, %.2f)'
                               % (msg.pose.position.x, msg.pose.position.y))

        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error('nav2 action server 없음')
            self.finish('nav2 서버 없음')
            return

        goal = NavigateToPose.Goal()
        goal.pose = msg

        self.get_logger().info('[4] nav2 로 goal 전송')
        send_future = self.nav_client.send_goal_async(goal)
        send_future.add_done_callback(self.nav_response_cb)
        self.set_state('NAVIGATING')

    def nav_response_cb(self, future):
        handle = future.result()
        if not handle.accepted:
            self.get_logger().error('nav2 가 goal 을 거부함')
            self.finish('goal 거부')
            return

        self.get_logger().info('[5] goal 수락됨. 이동 중.')
        self.nav_goal_handle = handle
        handle.get_result_async().add_done_callback(self.nav_result_cb)

    def nav_result_cb(self, future):
        status = future.result().status

        if status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warn('[6-X] 이동 실패 (status=%d)' % status)
            self.finish('이동 실패')
            return

        self.get_logger().info('[6] 도착. 2차 촬영 요청.')
        msg = Bool()
        msg.data = True
        self.capture_req_pub.publish(msg)
        self.set_state('CAPTURING')

    # ================= 감시 =================

    def watchdog(self):
        """각 상태에 너무 오래 머무르면 빠져나온다. 시간 기반 전환도 여기서 한다."""
        if self.state == 'IDLE':
            return

        t = self.elapsed()

        if self.state == 'PAUSING':
            if t >= self.settle_time:
                self.request_locate()

        elif self.state == 'LOCATING':
            if t >= self.locate_timeout:
                self.get_logger().warn('좌표가 안 온다 (%.1fs)' % t)
                self.finish('좌표 timeout')

        elif self.state == 'NAVIGATING':
            if t >= self.nav_timeout:
                self.get_logger().warn('이동이 안 끝난다 (%.1fs). 취소.' % t)
                if self.nav_goal_handle is not None:
                    self.nav_goal_handle.cancel_goal_async()
                self.finish('이동 timeout')

        elif self.state == 'CAPTURING':
            if t >= self.capture_time:
                self.finish('정상 완료')


def main():
    rclpy.init()
    node = ObserveCoordinator()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()