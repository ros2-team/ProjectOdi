#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32MultiArray
from odi_interfaces.msg import DetectedObject


class TrackerNode(Node):
    def __init__(self):
        super().__init__('tracker_node')

        self.declare_parameter('cx', 157.2)
        self.declare_parameter('cy', 120.0)
        self.declare_parameter('dead', 20)
        self.declare_parameter('step', 3.0)
        self.declare_parameter('pan_dir', -1)
        self.declare_parameter('tilt_dir', 1)

        self.cx = self.get_parameter('cx').value
        self.cy = self.get_parameter('cy').value
        self.dead = self.get_parameter('dead').value
        self.step = self.get_parameter('step').value
        self.pan_dir = self.get_parameter('pan_dir').value
        self.tilt_dir = self.get_parameter('tilt_dir').value

        self.pan_min, self.pan_max = 20.0, 155.0
        self.tilt_min, self.tilt_max = 5.0, 85.0

        self.pan = 80.0
        self.tilt = 65.0

        self.target = None
        self.fresh = False

        self.pub = self.create_publisher(
            Int32MultiArray, '/pan_tilt/cmd', 10)
        self.create_subscription(
            DetectedObject, '/yolo/detection', self.on_detection, 10)
        self.create_timer(0.05, self.on_timer)

        self.publish()   # 시작할 때 중립 한 번

    def on_detection(self, msg):
        self.target = (msg.center_x, msg.center_y)
        self.fresh = True

    def on_timer(self):
        if not self.fresh:
            return
        self.fresh = False

        u, v = self.target
        moved = False

        err_x = u - self.cx
        if abs(err_x) > self.dead:
            d = self.step if err_x > 0 else -self.step
            self.pan += d * self.pan_dir
            self.pan = max(self.pan_min, min(self.pan_max, self.pan))
            moved = True

        err_y = v - self.cy
        if abs(err_y) > self.dead:
            d = self.step if err_y > 0 else -self.step
            self.tilt += d * self.tilt_dir
            self.tilt = max(self.tilt_min, min(self.tilt_max, self.tilt))
            moved = True

        if moved:
            self.publish()
            self.get_logger().info(
                f'err=({err_x:.0f},{err_y:.0f}) '
                f'-> pan={self.pan:.0f} tilt={self.tilt:.0f}')

    def publish(self):
        m = Int32MultiArray()
        m.data = [int(round(self.pan)), int(round(self.tilt))]
        self.pub.publish(m)


def main():
    rclpy.init()
    node = TrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()