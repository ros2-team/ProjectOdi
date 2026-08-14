#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.action import CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from odi_interfaces.action import Explore


class MockExploreServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_explore_server")

        self.callback_group = ReentrantCallbackGroup()

        self.action_server = ActionServer(
            self,
            Explore,
            "/explore",
            execute_callback = self.execute_callback,
            cancel_callback = self.cancel_callback,
            callback_group = self.callback_group,
        )

        self.get_logger().info(
            "Mock Explore Server is Running"
        )
    def cancel_callback(self,cancel_request):
        self.get_logger().info(
            "Explore cancel request received"
        )
        return CancelResponse.ACCEPT

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

        if request.mode == "FRONTIER":
            return self.run_frontier_mode(goal_handle)
        if request.mode == "ROAM":
            return self.run_roam_mode(goal_handle)
        self.get_logger().warning(
            f"Unknown explore mode : {request.mode}"
        )
        goal_handle.abort()

        result = Explore.Result()
        result.status = "FAILED"
        result.visited_area_id = ""
        result.message = (
            f"Unknown explore mode : {request.mode}"
        )

        return result

    def run_frontier_mode(
            self,
            goal_handle,
    ) -> Explore.Result:

        feedback = Explore.Feedback()
        for index in range(5):
            if goal_handle.is_cancel_requested:
                self.get_logger().info(
                    "Frontier exploration canceled"
                )
                goal_handle.canceled()
                result = Explore.Result()
                result.status = "CANCELED"
                result.visited_area_id = (
                    f"frontier_{index + 1}"
                )
                result.message = (
                    f"Frontier exploration canceled"
                )
                return result

            feedback.current_area_id = (
                f"frontier_{index + 1}"
            )
            feedback.progress = (
                (index + 1) / 5.0
            )
            goal_handle.publish_feedback(
                feedback
            )
            self.get_logger().info(
                "\nFrontier feedback::\n"
                f"area = {feedback.current_area_id}\n"
                f"progress = {feedback.progress:.2f}"
            )
            time.sleep(1.0)

        self.get_logger().info(
            "No more frontier candidates"
        )
        goal_handle.succeed()
        result = Explore.Result()
        result.status = "FRONTIER_EXHAUSTED"
        result.visited_area_id = "frontier_end"
        result.message = (
            "No more frontier candidates"
        )
        return result

    def run_roam_mode(
        self,
        goal_handle,
    ) -> Explore.Result:

        feedback = Explore.Feedback()

        progress = 0.0
        roam_index = 1

        while rclpy.ok():

            if goal_handle.is_cancel_requested:
                self.get_logger().info(
                    "Roaming canceled"
                )

                goal_handle.canceled()

                result = Explore.Result()
                result.status = "CANCELED"
                result.visited_area_id = (
                    f"roam_{roam_index}"
                )
                result.message = (
                    "Roaming canceled."
                )

                return result

            progress += 0.05

            feedback.current_area_id = (
                f"roam_{roam_index}"
            )

            feedback.progress = progress

            goal_handle.publish_feedback(
                feedback
            )

            self.get_logger().info(
                "::Roam feedback::\n"
                f"area = {feedback.current_area_id}\n"
                f"progress = {progress:.2f}"
            )

            time.sleep(1.0)

            if progress >= 1.0:
                break

            roam_index += 1

        goal_handle.succeed()

        result = Explore.Result()
        result.status = "COMPLETED"
        result.visited_area_id = (
            f"roam_{roam_index}"
        )
        result.message = (
            "Roaming completed."
        )

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockExploreServer()

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


if __name__ == "__main__":
    main()
