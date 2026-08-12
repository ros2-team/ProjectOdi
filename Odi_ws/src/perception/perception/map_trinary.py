import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
from nav_msgs.msg import OccupancyGrid

# 약하게 받고 강하게 준다
SUB_QOS = QoSProfile(depth=5,
                     reliability=QoSReliabilityPolicy.RELIABLE,
                     durability=QoSDurabilityPolicy.VOLATILE)

PUB_QOS = QoSProfile(depth=1,
                     reliability=QoSReliabilityPolicy.RELIABLE,
                     durability=QoSDurabilityPolicy.TRANSIENT_LOCAL)


class MapTrinary(Node):
    """cartographer의 확률 기반 OccupancyGrid를 0/100/-1 trinary로 변환해 재발행."""

    def __init__(self):
        super().__init__('map_trinary')
        self.declare_parameter('thresh', 65)

        self.pub = self.create_publisher(OccupancyGrid, 'map_trinary', PUB_QOS)
        self.create_subscription(OccupancyGrid, 'map', self.cb, SUB_QOS)

        self.get_logger().info('map_trinary started')

    def cb(self, msg):
        # 매번 읽는다 → ros2 param set으로 런타임 변경 가능
        thresh = self.get_parameter('thresh').value

        out = OccupancyGrid()
        out.header = msg.header
        out.info = msg.info
        out.data = [-1 if v < 0 else (100 if v >= thresh else 0) for v in msg.data]
        self.pub.publish(out)


def main(args=None):
    rclpy.init(args=args)
    node = MapTrinary()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()