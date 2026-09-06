#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.action import CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from odi_interfaces.action import ObserveObject
from odi_interfaces.msg import ObservationResult
from odi_interfaces.msg import SemanticLabel


class MockObservationServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_observation_server")

        self.callback_group = ReentrantCallbackGroup()

        self.action_server = ActionServer(
            self,
            ObserveObject,
            "/observe_object",
            execute_callback = self.execute_callback,
            cancel_callback = self.cancel_callback,
            callback_group = self.callback_group,
        )

        self.get_logger().info(
            "\nMock Observation Server is Running"
        )

    def cancel_callback(
            self,
            cancel_request,
    ):
        self.get_logger().info(
            "\nObservation cancel request received"
        )
        return CancelResponse.ACCEPT

    def execute_callback(
        self,
        goal_handle,
    ) -> ObserveObject.Result:

        encounter = goal_handle.request.encounter
        decision = goal_handle.request.decision

        self.get_logger().info(
            "::Observation requested::\n"
            f"detection_id = {encounter.detection_id}\n"
            f"object_name = "
            f"{encounter.label.object_name}\n"
            f"curiosity_score = "
            f"{decision.curiosity_score:.2f}"
        )

        feedback = ObserveObject.Feedback()

        stages = [
            (
                "SELECTING_VIEWPOINT",
                0.15,
                "Selecting observation viewpoint",
            ),
            (
                "ALIGNING",
                0.30,
                "Aligning with object",
            ),
            (
                "CAPTURING",
                0.55,
                "Capturing diary images",
            ),
            (
                "DETAILED_LABELING",
                0.75,
                "Generating detailed semantic label",
            ),
            (
                "SAVING_DATABASE",
                0.90,
                "Saving observation to database",
            ),
            (
                "COMPLETED",
                1.00,
                "Observation completed",
            ),
        ]

        for stage, progress, message in stages:
            if goal_handle.is_cancel_requested:
                self.get_logger().info(
                    "Observation canceled"
                )
                goal_handle.canceled()

                result = ObserveObject.Result()
                result.result.success = False
                result.result.detection_id = (
                    goal_handle.request.encounter.detection_id
                )
                result.result.failure_reason = (
                    "Canceled by Behavior executor"
                )
                return result
            feedback.stage = stage
            feedback.progress = progress
            feedback.message = message

            goal_handle.publish_feedback(feedback)

            time.sleep(0.7)

        if goal_handle.is_cancel_requested:
            self.get_logger().info(
                "Observation canceled"
            )
            goal_handle.canceled()

            result = ObserveObject.Result()
            result.result.success = False
            result.result.detection_id = (
                goal_handle.request.encounter.detection_id
            )
            result.result.failure_reason = (
                "Canceled by behavior Executor"
            )
            return result

        detailed_label = SemanticLabel()

        detailed_label.object_name = (
            encounter.label.object_name
        )

        detailed_label.object_primary_color = (
            encounter.label.object_primary_color
        )

        detailed_label.object_secondary_color = (
            encounter.label.object_secondary_color
        )

        detailed_label.object_material = "plastic"
        detailed_label.object_shape = "detailed shape"
        detailed_label.object_condition = "normal"

        detailed_label.object_special_features = [
            "mock detailed feature 1",
            "mock detailed feature 2",
        ]

        detailed_label.raw_json = "{}"

        observation = ObservationResult()

        observation.detection_id = (
            encounter.detection_id
        )

        observation.success = True

        observation.image_paths = [
            f"/tmp/{encounter.detection_id}_observe_01.jpg",
            f"/tmp/{encounter.detection_id}_observe_02.jpg",
        ]

        observation.representative_image_path = (
            f"/tmp/{encounter.detection_id}_observe_01.jpg"
        )

        observation.detailed_label = detailed_label

        observation.diary_summary = (
            "Mock detailed observation completed."
        )

        observation.saved_to_database = True
        observation.memory_id = "mock_memory_001"

        now = self.get_clock().now().to_msg()

        observation.started_at = now
        observation.completed_at = now

        observation.failure_reason = ""

        result = ObserveObject.Result()
        result.result = observation

        goal_handle.succeed()

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockObservationServer()

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
