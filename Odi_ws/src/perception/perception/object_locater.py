import math

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.duration import Duration

from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PointStamped
from odi_interfaces.msg import DetectedObject

import tf2_ros
from tf2_geometry_msgs import do_transform_point
from rclpy.qos import qos_profile_sensor_data

class ObjectLocator(Node):
    """
    bbox 픽셀 좌표 + LiDAR 거리 + TF 로
    물체의 map 좌표 (x, y) 를 추정한다.
    로봇이 물체 위치까지 이동할 필요 없음.
    """

    def __init__(self):
        super().__init__('object_locator')

        # ================== 네가 채울 값 ==================
        self.scan_topic = '/scan'
        self.yolo_topic = '/observe/locate_request'
        
        self.image_width = 320    # YOLO 에 들어가는 실제 이미지 가로 픽셀
        self.fx = 270.2           # bearing_probe 로 구한 값으로 교체할 것
        self.cx = 157.2           # image_width / 2

        self.lidar_frame = 'base_scan'
        self.map_frame = 'map'

        self.r_min = 0.16
        self.r_max = 8.0

        self.standoff = 0.6   # 물체 앞 몇 m 지점에 설 것인지

        # ---- 테스트 모드 (검증 끝나면 False 로) ----
        # YOLO 가 찍어준 bbox 의 좌/우 x 픽셀을 손으로 넣고
        # 2초마다 좌표를 계산해서 로그로 출력한다.
        # self.test_mode = True
        # self.test_u_left = 58.0
        # self.test_u_right = 72.0
        # # =================================================
        ############################################# 구독 #################################################
        self.latest_scan = None
        self.create_subscription(LaserScan, self.scan_topic, self.scan_cb, qos_profile_sensor_data)

        self.create_subscription(DetectedObject, self.yolo_topic, self.image_cb, 10)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)


        self.create_timer(2.0, self.test_tick)
        self.get_logger().info('test_mode ON (u_left=%.1f, u_right=%.1f)'
                                           % (self.test_u_left, self.test_u_right))
        
        # if self.test_mode:
        #     self.create_timer(2.0, self.test_tick)
        #     self.get_logger().info('test_mode ON (u_left=%.1f, u_right=%.1f)'
        #                            % (self.test_u_left, self.test_u_right))

    # ---------------- 콜백은 저장만 ----------------

    def scan_cb(self, msg):
        self.latest_scan = msg

    def image_cb(self, msg):
        if msg:
            self.center_x = msg.center_x
            self.width = msg.width
        else:
            pass

        self.u_left = self.center_x - (self.width // 2)
        self.u_right = self.center_x + (self.width // 2)

    def test_tick(self):
        result = self.locate(self.u_left, self.u_right)

        if result:
            pt = PointStamped()
            pt.header.frame_id = self.map_frame
            pt.header.stamp = self.get_clock().now().to_msg()
            pt.point.x = result['map_x']
            pt.point.y = result['map_y']
            pt.point.z = 0.0

    # ---------------- 계산 ----------------

    def pixel_to_bearing(self, u):
        """이미지 u 좌표(픽셀) -> 로봇 정면 기준 각도(rad). 왼쪽이 +"""
        return math.atan2(self.cx - u, self.fx)

    def range_between(self, scan, ang_a, ang_b):
        """두 각도 사이 구간의 scan 값들 중 median. 유효값 없으면 None"""
        lo = min(ang_a, ang_b)
        hi = max(ang_a, ang_b)

        vals = []
        for i in range(len(scan.ranges)):
            a = scan.angle_min + i * scan.angle_increment
            a = math.atan2(math.sin(a), math.cos(a))   # -pi ~ pi 정규화

            if lo <= a <= hi:
                r = scan.ranges[i]
                if math.isfinite(r) and self.r_min <= r <= self.r_max:
                    vals.append(r)

        if not vals:
            return None

        vals.sort()
        return vals[len(vals) // 2]

    def locate(self, u_left, u_right):
        """
        bbox 의 좌/우 x 픽셀을 받아 물체의 map 좌표를 추정한다.
        반환: dict 또는 None

        ※ 로봇이 정지한 상태에서 호출할 것.
           이미지와 scan 을 시간 동기화하지 않기 때문에
           움직이는 중이면 방향과 거리가 어긋난다.
        """
        scan = self.latest_scan
        if scan is None:
            self.get_logger().warn('아직 scan 을 못 받음')
            return None

        u_center = (u_left + u_right) / 2.0

        # bbox 가장자리는 배경이 섞이므로 안쪽 50% 구간만 사용
        quarter = (u_right - u_left) / 4.0
        ang_a = self.pixel_to_bearing(u_center - quarter)
        ang_b = self.pixel_to_bearing(u_center + quarter)

        r = self.range_between(scan, ang_a, ang_b)
        if r is None:
            self.get_logger().warn('그 방향에 유효한 scan 값이 없음')
            return None

        theta = self.pixel_to_bearing(u_center)

        pt = PointStamped()
        pt.header.frame_id = self.lidar_frame
        # stamp 를 0 으로 두면 "가장 최신 TF" 를 쓴다.
        # scan 의 stamp 를 넣으면 transform cache 문제로 자주 실패한다.
        pt.header.stamp = Time().to_msg()
        pt.point.x = r * math.cos(theta)
        pt.point.y = r * math.sin(theta)
        pt.point.z = 0.0

        try:
            tf = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.lidar_frame,
                Time(),
                timeout=Duration(seconds=0.5),
            )
        except Exception as e:
            self.get_logger().warn('TF lookup 실패: %s' % str(e))
            return None

        out = do_transform_point(pt, tf)

         # ---- standoff goal 계산 ----
        goal_r = r - self.standoff
        if goal_r < 0.0:
            self.get_logger().warn('이미 standoff 안쪽 (r=%.2f)' % r)
            goal_r = 0.0

        gp = PointStamped()
        gp.header.frame_id = self.lidar_frame
        gp.header.stamp = Time().to_msg()
        gp.point.x = goal_r * math.cos(theta)
        gp.point.y = goal_r * math.sin(theta)
        gp.point.z = 0.0

        goal = do_transform_point(gp, tf)

        # goal 지점에서 물체를 바라보는 방향
        goal_yaw = math.atan2(out.point.y - goal.point.y,
                              out.point.x - goal.point.x)

        result = {
            'map_x': out.point.x,
            'map_y': out.point.y,
            'goal_x': goal.point.x,
            'goal_y': goal.point.y,
            'goal_yaw': goal_yaw,
            'range': r,
            'bearing': theta,
        }

        self.get_logger().info(
            'object(%.2f, %.2f) -> goal(%.2f, %.2f) yaw=%+.1fdeg  r=%.2fm'
            % (out.point.x, out.point.y, goal.point.x, goal.point.y,
               math.degrees(goal_yaw), r))
        return result

    
        # result = {
        #     'map_x': out.point.x,
        #     'map_y': out.point.y,
        #     'range': r,          # 로봇 기준 거리 (m)
        #     'bearing': theta,    # 로봇 기준 각도 (rad), 왼쪽이 +
        # }

        # self.get_logger().info(
        #     'object -> range=%.2fm  bearing=%+.1fdeg  map(%.2f, %.2f)'
        #     % (r, math.degrees(theta), result['map_x'], result['map_y'])
        # )
        # return result


def main():
    rclpy.init()
    node = ObjectLocator()

    # 검증이 끝나면 test_mode 를 끄고,
    # 네 detection 콜백에서 bbox 좌/우 x 픽셀을 뽑아
    # node.locate(u_left, u_right) 를 호출하도록 연결하면 된다.

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()