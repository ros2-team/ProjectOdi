
import time

import rclpy
from rclpy.action import (
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from odi_interfaces.action import Reflect


class ReflectionNode(Node):

    def __init__(self) -> None:
        super().__init__("reflection_node")

        self.callback_group = ReentrantCallbackGroup()

        self.action_server = ActionServer(
            self,
            Reflect,
            "/reflect",
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )

        self.get_logger().info(
            "Reflection Action Server is running"
        )

    def goal_callback(
        self,
        goal_request: Reflect.Goal,
    ) -> GoalResponse:

        session_id = goal_request.session_id.strip()

        self.get_logger().info(
            "::Reflect goal received::\n"
            f"session_id = {session_id}"
        )

        if not session_id:
            self.get_logger().warning(
                "Reflect goal rejected: session_id is empty"
            )
            return GoalResponse.REJECT

        return GoalResponse.ACCEPT

    def cancel_callback(
        self,
        goal_handle,
    ) -> CancelResponse:

        self.get_logger().info(
            "::Reflect cancel requested::\n"
            f"session_id = {goal_handle.request.session_id}"
        )

        return CancelResponse.ACCEPT

    def execute_callback(
        self,
        goal_handle,
    ) -> Reflect.Result:

        session_id = goal_handle.request.session_id

        stages = [
            (
                "COLLECTING",
                0.25,
                "Collecting exploration records.",
            ),
            (
                "GENERATING",
                0.60,
                "Generating exploration diary.",
            ),
            (
                "SAVING",
                0.85,
                "Saving exploration diary.",
            ),
        ]

        for stage, progress, message in stages:
            if goal_handle.is_cancel_requested:
                return self.finish_canceled_goal(goal_handle)

            feedback = Reflect.Feedback()
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

        if goal_handle.is_cancel_requested:
            return self.finish_canceled_goal(goal_handle)

        diary_text = (
            "오늘은 새로운 공간을 천천히 탐험했다. "
            "바닥 가까이에서 파란 뚜껑이 달린 물병을 발견했고, "
            "조금 더 이동한 뒤에는 벽 옆에 놓인 검은색 가방도 살펴보았다. "
            "처음 보는 물체들을 가까이에서 관찰할 수 있어 흥미로운 탐험이었다."
        )

        result = Reflect.Result()
        result.success = True
        result.diary_id = "test_diary_001"
        result.diary_text = diary_text
        result.message = (
            f"Test diary generated for session {session_id}"
        )

        goal_handle.succeed()

        self.get_logger().info(
            "::Reflection completed::\n"
            f"diary_id = {result.diary_id}\n"
            f"diary_text = {result.diary_text}"
        )

        return result

    def finish_canceled_goal(
        self,
        goal_handle,
    ) -> Reflect.Result:

        goal_handle.canceled()

        result = Reflect.Result()
        result.success = False
        result.diary_id = ""
        result.diary_text = ""
        result.message = "Reflection canceled"

        self.get_logger().info(
            "Reflection goal canceled"
        )

        return result

    def destroy_node(self) -> None:
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)

    node = ReflectionNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)

    try:
        executor.spin()

    except KeyboardInterrupt:
        pass

    finally:
        executor.shutdown()
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
