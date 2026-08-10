import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

class TestSenderNode(Node):
    def __init__(self):
        super().__init__('test_sender_node')

        self.publisher = self.create_publisher(String, 'detected_object', 10)

        self.timer = self.create_timer(2.0, self.publish_data)
        self.count = 0

    def publish_data(self):
        sample = {
            'object_name': 'cup',
            'object_primary_color': 'white',
            'object_secondary_color': 'blue',
            'object_material': 'ceramic',
            'object_shape': 'cylinder',
            'object_condition': 'clean',
            'object_special_features': ['손잡이 있음', '파란 무늬'],
            'raw_json': {'source': 'yolo', 'confidence': 0.92},
        }

        msg = String()

        msg.data = json.dumps(sample, ensure_ascii=False)
        self.publisher.publish(msg)

        self.count += 1
        self.get_logger().info(f"발행 #{self.count}: {sample['object_name']}")


def main(args=None):
    rclpy.init(args = args)
    node = TestSenderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()