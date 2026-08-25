import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from rclpy.qos import qos_profile_sensor_data

class BearingProbe(Node):
    """
    앞쪽 부채꼴 안에서 '가장 가까운 점'의 각도와 거리를 1초마다 출력한다.
    fx 를 구할 때만 쓰는 임시 도구. 구하고 나면 안 써도 된다.

    전제: 로봇 앞 부채꼴 안에 측정용 물체 하나만 있어야 한다.
         (그 물체가 그 구간에서 제일 가까운 점이어야 함)
    """

    def __init__(self):
        super().__init__('bearing_probe')

        self.scan_topic = '/scan'
        self.sector_deg = 45.0   # 앞쪽 +-45도만 본다

        self.latest_scan = None
        self.create_subscription(LaserScan, self.scan_topic, self.scan_cb, qos_profile_sensor_data)
        self.create_timer(1.0, self.report)

        # LDS-02 실제 스펙 (드라이버가 발행하는 range_min/max가 부정확함)
        self.r_min = 0.16
        self.r_max = 8.0

        # self.get_logger().info("라이다 ")

    def scan_cb(self, msg):
        self.latest_scan = msg

    def report(self):
        scan = self.latest_scan

        if scan is None:
            self.get_logger().warn('아직 scan 을 못 받음')
            return

        limit = math.radians(self.sector_deg)
        best_r = None
        best_a = None

        for i in range(len(scan.ranges)):
            a = scan.angle_min + i * scan.angle_increment
            # -pi ~ pi 로 정규화
            a = math.atan2(math.sin(a), math.cos(a))

            if -limit <= a <= limit:
                r = scan.ranges[i]
                if math.isfinite(r) and self.r_min <= r <= self.r_max:
                    if best_r is None or r < best_r:
                        best_r = r
                        best_a = a

        if best_r is None:
            self.get_logger().warn('부채꼴 안에 유효한 점이 없음')
            return

        self.get_logger().info(
            'closest -> bearing = %+.2f deg,  range = %.3f m'
            % (math.degrees(best_a), best_r)
        )


def main():
    rclpy.init()
    node = BearingProbe()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()