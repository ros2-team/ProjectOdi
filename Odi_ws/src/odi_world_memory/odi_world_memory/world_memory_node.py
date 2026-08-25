
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup

from odi_world_memory.database import Database
class WorldMemoryNode(Node):
    def __init__(self):
        super().__init__('world_memory_node')

        self.callback_group = ReentrantCallbackGroup()
        self.database = Database()

        database_name = self.database.test_connection()

        self.get_logger().info(
            f"Connected to Mysql database : {database_name}"
        )
        self.get_logger().info("Odi world memory node is runing")

def main(args=None):
    rclpy.init(args=args)

    node = WorldMemoryNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
