#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node

from odi_interfaces.action import Reflect


class MockReflectServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_reflect_server")

        self.action_server = ActionServer(
            self,
            Reflect,
            "/reflect",
            self.execute_callback,
        )

        self.get_logger().info(
            "Mock Reflect Server is Running"
        )

    def execute_callback(
        self,
        goal_handle,
    ) -> Reflect.Result:

        request = goal_handle.request

        self.get_logger().info(
            "::Reflect requested::\n"
            f"session_id = {request.session_id}"
        )

        feedback = Reflect.Feedback()

        stages = [
            (
                "COLLECTING",
                0.25,
                "Collecting exploration records.",
            ),
            (
                "GENERATING",
                0.55,
                "Generating exploration diary.",
            ),
            (
                "SAVING",
                0.85,
                "Saving exploration diary.",
            ),
            (
                "COMPLETED",
                1.0,
                "Exploration diary completed.",
            ),
        ]

        for stage, progress, message in stages:

            feedback.stage = stage
            feedback.progress = progress
            feedback.message = message

            goal_handle.publish_feedback(feedback)

            self.get_logger().info(
                "::Reflect feedback::\n"
                f"stage = {stage}\n"
                f"progress = {progress:.2f}\n"
                f"message = {message}"
            )

            time.sleep(1.0)

        goal_handle.succeed()

        result = Reflect.Result()
        result.success = True
        result.diary_id = "diary_001"

        result.diary_text = (
            "오늘은 새로운 공간을 탐험했다. "
            "흥미로운 물체를 발견하고 가까이 다가가 "
            "자세히 관찰했다. "
            "이제 돌아다니는 것도 조금 지친다."
        )

        result.message = (
            "Mock exploration diary generated."
        )

        self.get_logger().info(
            "Mock Reflect completed"
        )

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockReflectServer()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
