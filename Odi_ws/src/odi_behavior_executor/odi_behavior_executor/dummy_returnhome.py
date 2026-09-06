#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node

from odi_interfaces.action import ReturnHome


class MockReturnHomeServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_return_home_server")

        self.action_server = ActionServer(
            self,
            ReturnHome,
            "/return_home",
            self.execute_callback,
        )

        self.get_logger().info(
            "Mock Return Home Server is Running"
        )

    def execute_callback(
        self,
        goal_handle,
    ) -> ReturnHome.Result:

        request = goal_handle.request

        self.get_logger().info(
            "::Return Home requested::\n"
            f"reason = {request.reason}"
        )

        feedback = ReturnHome.Feedback()

        stages = [
            (
                "PLANNING",
                0.2,
                "Planning route to home position.",
            ),
            (
                "MOVING",
                0.5,
                "Moving toward home position.",
            ),
            (
                "APPROACHING",
                0.8,
                "Approaching home position.",
            ),
            (
                "ARRIVED",
                1.0,
                "Arrived at home position.",
            ),
        ]

        for stage, progress, message in stages:

            feedback.stage = stage
            feedback.progress = progress
            feedback.message = message

            goal_handle.publish_feedback(
                feedback
            )

            self.get_logger().info(
                "::Return Home feedback::\n"
                f"stage = {stage}\n"
                f"progress = {progress:.2f}\n"
                f"message = {message}"
            )

            time.sleep(1.0)

        goal_handle.succeed()

        result = ReturnHome.Result()
        result.success = True
        result.message = (
            "Robot returned to home position."
        )

        self.get_logger().info(
            "Mock Return Home completed"
        )

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockReturnHomeServer()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
