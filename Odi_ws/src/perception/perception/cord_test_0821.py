import math

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.duration import Duration

from std_msgs.msg import Bool
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

# ▼▼▼ object_locator 와 같은 타입이어야 함 ▼▼▼
from odi_interfaces.msg import DetectedObject
# ▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲▲


class ObserveCoordinator(Node):
    """
    관찰 시퀀스를 혼자 담당하는 노드.

    IDLE ─(detection)─▶ PAUSING ─▶ LOCATING ─▶ CAPTURING_1ST
                                                     │
                                                NAVIGATING
                                                     │
                                              CAPTURING_2ND ─▶ IDLE

    다른 노드는 자기 일만 한다:
      YOLO            : bbox 발행 + 촬영 요청이 올 때만 crop 발행
      object_locator  : 좌표 계산만
      explore         : 탐사만
    순서는 전부 이 노드가 안다.
    """

    def __init__(self):
        super().__init__('observe_coordinator')

        # ================ 토픽 이름 ================
        self.detection_topic = '/yolo/detection'          # ← YOLO 발행 토픽으로 맞출 것
        self.locate_request_topic = '/observe/locate_request'
        self.approach_goal_topic = '/observe/approach_goal'
        self.capture_1st_topic = '/observe/capture_1st'   # 원거리 촬영 요청
        self.capture_2nd_topic = '/observe/capture_2nd'   # 근접 촬영 요청
        self.explore_resume_topic = '/explore/resume'

        # ================ 시간 설정 (초) ================
        # watchdog 이 1Hz 라서 실제 분해능은 약 1초다. 값을 1초 미만으로
        # 줘도 의미가 없다.
        self.settle_time = 2.0        # 탐사 정지 후 로봇이 멈출 때까지 기다림
        self.locate_timeout = 5.0     # 좌표가 안 오면 포기
        self.capture_1st_time = 2.0   # 1차 촬영 신호 후 nav2 로 넘어가기까지
        self.nav_timeout = 120.0      # 이동이 안 끝나면 포기
        self.arrive_settle = 1.0      # 도착 직후 흔들림이 가라앉을 때까지
        self.capture_2nd_time = 4.0   # 2차 상태 전체 길이 (arrive_settle 포함)
        self.cooldown = 15.0          # 관찰 종료 후 재감지를 무시하는 시간

        # ================ 중복 관찰 방지 ================
        # object_locator 의 standoff 와 반드시 같은 값이어야 한다.
        # 이 값으로 goal 에서 물체 위치를 역산하기 때문.
        self.standoff = 0.6
        self.visit_radius = 0.7     # 이 반경 안이면 같은 물체로 본다

        # ================ 상태 ================
        self.state = 'IDLE'
        self.state_entered_at = self.get_clock().now()
        self.cooldown_until = self.get_clock().now()

        self.pending_detection = None
        self.pending_object = None
        self.pending_goal = None    # 1차 촬영 동안 들고 있다가 나중에 nav2 로 보낸다
        self.captured_2nd = False   # 2차 촬영을 이미 쐈는지
        self.visited = []           # 관찰을 마친 물체들의 map 좌표
        self.nav_goal_handle = None

        ############################################# sub ############################################
        self.create_subscription(DetectedObject, self.detection_topic, self.detection_cb, 10)
        self.create_subscription(PoseStamped, self.approach_goal_topic, self.approach_goal_cb, 10)

        ############################################# pub #############################################
        self.resume_pub = self.create_publisher(Bool, self.explore_resume_topic, 10)
        self.locate_req_pub = self.create_publisher(DetectedObject, self.locate_request_topic, 10)
        self.capture_1st_pub = self.create_publisher(Bool, self.capture_1st_topic, 10)
        self.capture_2nd_pub = self.create_publisher(Bool, self.capture_2nd_topic, 10)

        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        self.create_timer(1.0, self.watchdog)

        self.get_logger().info(
            'observe_coordinator 시작. standoff=%.2f visit_radius=%.2f cooldown=%.1fs'
            % (self.standoff, self.visit_radius, self.cooldown))

    # ================= 상태 관리 =================

    def set_state(self, new_state):
        self.get_logger().info('상태 전환: %s -> %s' % (self.state, new_state))
        self.state = new_state
        self.state_entered_at = self.get_clock().now()

    def elapsed(self):
        dt = self.get_clock().now() - self.state_entered_at
        return dt.nanoseconds / 1e9

    def finish(self, reason):
        """성공이든 실패든 모든 종료는 여기로 온다. 반드시 탐사를 재개시킨다."""
        self.get_logger().info('관찰 종료 (%s). 탐사 재개.' % reason)
        self.pending_detection = None
        self.pending_object = None
        self.pending_goal = None
        self.captured_2nd = False
        self.nav_goal_handle = None

        # 재개 직후 같은 물체가 다시 잡히는 걸 막는다
        self.cooldown_until = self.get_clock().now() + Duration(seconds=self.cooldown)

        self.publish_resume(True)
        self.set_state('IDLE')

    def publish_resume(self, value):
        msg = Bool()
        msg.data = value
        self.resume_pub.publish(msg)
        self.get_logger().info('/explore/resume <- %s' % value)

    def publish_capture(self, pub, label):
        """촬영 요청은 발행만 한다. 성공 여부는 알 수 없다."""
        msg = Bool()
        msg.data = True
        pub.publish(msg)
        self.get_logger().info('%s 촬영 요청 발행 -> %s' % (label, pub.topic_name))

    # ================= 1. 발견 =================

    def detection_cb(self, msg):
        if self.state != 'IDLE':
            return

        if self.get_clock().now() < self.cooldown_until:
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

    # ================= 3. 좌표 수신 → 중복 검사 → 1차 촬영 =================

    def approach_goal_cb(self, msg):
        if self.state != 'LOCATING':
            self.get_logger().warn('LOCATING 상태가 아닌데 goal 이 왔다. 무시.')
            return

        gx = msg.pose.position.x
        gy = msg.pose.position.y

        # quaternion -> yaw. 그 방향으로 standoff 만큼 나가면 물체 위치다.
        # goal 좌표로 중복을 판단하면 안 된다. 같은 물체라도
        # 접근 방향이 다르면 goal 이 전혀 다른 자리에 찍히기 때문.
        yaw = 2.0 * math.atan2(msg.pose.orientation.z, msg.pose.orientation.w)
        ox = gx + self.standoff * math.cos(yaw)
        oy = gy + self.standoff * math.sin(yaw)

        for (vx, vy) in self.visited:
            if math.hypot(ox - vx, oy - vy) < self.visit_radius:
                self.get_logger().info(
                    '이미 관찰한 물체 (%.2f, %.2f). 건너뜀.' % (ox, oy))
                self.finish('중복 물체')
                return

        self.get_logger().info(
            '[3] goal 수신: (%.2f, %.2f)  물체 추정: (%.2f, %.2f)'
            % (gx, gy, ox, oy))

        # nav2 가 죽어 있으면 1차 촬영(=VLM 호출)을 낭비하지 않고 여기서 끝낸다
        if not self.nav_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error('nav2 action server 없음')
            self.finish('nav2 서버 없음')
            return

        self.pending_object = (ox, oy)
        self.pending_goal = msg

        # 로봇은 아직 정지 상태다. 원거리 촬영은 여기서 한다.
        self.get_logger().info('[4] 1차 촬영 요청 (원거리)')
        self.publish_capture(self.capture_1st_pub, '1차')
        self.set_state('CAPTURING_1ST')

        # 나중에 호기심 판단 노드를 붙이면
        # CAPTURING_1ST 다음에 JUDGING 상태를 하나 끼워 넣으면 된다.

    # ================= 4. nav2 이동 =================

    def send_nav_goal(self):
        goal = NavigateToPose.Goal()
        goal.pose = self.pending_goal

        self.get_logger().info('[5] nav2 로 goal 전송')
        send_future = self.nav_client.send_goal_async(goal)
        send_future.add_done_callback(self.nav_response_cb)
        self.set_state('NAVIGATING')

    def nav_response_cb(self, future):
        handle = future.result()
        if not handle.accepted:
            self.get_logger().error('nav2 가 goal 을 거부함')
            self.finish('goal 거부')
            return

        self.get_logger().info('[6] goal 수락됨. 이동 중.')
        self.nav_goal_handle = handle
        handle.get_result_async().add_done_callback(self.nav_result_cb)

    def nav_result_cb(self, future):
        status = future.result().status

        if status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warn('[7-X] 이동 실패 (status=%d)' % status)
            self.finish('이동 실패')
            return

        # 관찰을 마친 물체로 기록. 다음부터 이 근처는 건너뛴다.
        if self.pending_object is not None:
            self.visited.append(self.pending_object)
            self.get_logger().info(
                '관찰 기록 추가 (%.2f, %.2f). 누적 %d개'
                % (self.pending_object[0], self.pending_object[1],
                   len(self.visited)))

        self.get_logger().info('[7] 도착. 흔들림 가라앉기를 기다린다.')
        self.captured_2nd = False
        self.set_state('CAPTURING_2ND')

    # ================= 감시 =================

    def watchdog(self):
        """상태별 시간 초과 처리와 시간 기반 전환을 담당한다."""
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

        elif self.state == 'CAPTURING_1ST':
            if t >= self.capture_1st_time:
                self.send_nav_goal()

        elif self.state == 'NAVIGATING':
            if t >= self.nav_timeout:
                self.get_logger().warn('이동이 안 끝난다 (%.1fs). 취소.' % t)
                if self.nav_goal_handle is not None:
                    self.nav_goal_handle.cancel_goal_async()
                self.finish('이동 timeout')

        elif self.state == 'CAPTURING_2ND':
            # 도착 직후엔 차체가 흔들리므로 조금 기다렸다가 딱 한 번만 쏜다
            if not self.captured_2nd and t >= self.arrive_settle:
                self.get_logger().info('[8] 2차 촬영 요청 (근접)')
                self.publish_capture(self.capture_2nd_pub, '2차')
                self.captured_2nd = True

            if t >= self.capture_2nd_time:
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