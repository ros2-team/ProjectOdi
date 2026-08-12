#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node

from odi_interfaces.action import Explore


class MockExploreServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_explore_server")

        self.action_server = ActionServer(
            self,
            Explore,
            "/explore",
            self.execute_callback,
        )

        self.get_logger().info(
            "Mock Explore Server is Running"
        )

    def execute_callback(
        self,
        goal_handle,
    ) -> Explore.Result:

        request = goal_handle.request

        self.get_logger().info(
            "::Explore requested::\n"
            f"session_id = {request.session_id}\n"
            f"mode = {request.mode}"
        )

        feedback = Explore.Feedback()

        progress = 0.0
        area_index = 1

        while rclpy.ok():

            # Client에서 cancel 요청이 들어왔는지 확인
            if goal_handle.is_cancel_requested:
                self.get_logger().info(
                    "Explore cancel requested by client"
                )

                goal_handle.canceled()

                result = Explore.Result()
                result.status = "CANCELED"
                result.visited_area_id = (
                    f"area_{area_index}"
                )
                result.message = (
                    "Exploration canceled for object processing."
                )

                return result

            progress += 0.05

            feedback.current_area_id = (
                f"area_{area_index}"
            )

            feedback.progress = progress

            goal_handle.publish_feedback(
                feedback
            )

            self.get_logger().info(
                "::Explore feedback::\n"
                f"area = {feedback.current_area_id}\n"
                f"progress = {progress:.2f}"
            )

            time.sleep(1.0)

            if progress >= 1.0:
                break

            area_index += 1

        goal_handle.succeed()

        result = Explore.Result()
        result.status = "COMPLETED"
        result.visited_area_id = (
            f"area_{area_index}"
        )
        result.message = (
            "Mock exploration completed."
        )

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockExploreServer()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
