#!/usr/bin/env python3

import time

import rclpy
from rclpy.action import ActionServer
from rclpy.node import Node

from odi_interfaces.action import FirstEncounter
from odi_interfaces.msg import EncounterResult
from odi_interfaces.msg import SemanticLabel


class MockFirstEncounterServer(Node):
    """FirstEncounter.action 테스트용 가짜 서버."""

    def __init__(self) -> None:
        super().__init__("mock_first_encounter_server")

        self.action_server = ActionServer(
            self,
            FirstEncounter,
            "/first_encounter",
            self.execute_callback,
        )

        self.get_logger().info(
            "Mock First Encounter Server is Running."
        )

    def execute_callback(
        self,
        goal_handle,
    ) -> FirstEncounter.Result:
        target = goal_handle.request.target

        self.get_logger().info(
            "::First encounter requested::\n"
            f"id = {target.detection_id}\n"
            f"class = {target.class_name}"
        )

        feedback = FirstEncounter.Feedback()

        stages = [
            (
                "ALIGNING",
                0.2,
                "Aligning with the detected object.",
            ),
            (
                "APPROACHING",
                0.4,
                "Approaching the detected object.",
            ),
            (
                "CAPTURING",
                0.7,
                "Capturing the first encounter image.",
            ),
            (
                "LABELING",
                0.9,
                "Generating a semantic label.",
            ),
            (
                "COMPLETED",
                1.0,
                "First encounter completed.",
            ),
        ]

        for stage, progress, message in stages:
            feedback.stage = stage
            feedback.progress = progress
            feedback.message = message

            goal_handle.publish_feedback(feedback)

            time.sleep(1.0)

        encounter = EncounterResult()
        encounter.detection_id = target.detection_id
        encounter.success = True
        encounter.image_path = (
            f"/tmp/{target.detection_id}_encounter.jpg"
        )

        label = SemanticLabel()
        label.object_name = target.class_name
        label.object_primary_color = "blue"
        label.object_secondary_color = "white"
        label.object_material = "unknown"
        label.object_shape = "unknown"
        label.object_condition = "normal"
        label.object_special_features = [
            "mock generated label",
        ]
        label.raw_json = "{}"

        encounter.label = label

        now = self.get_clock().now().to_msg()
        encounter.started_at = now
        encounter.completed_at = now
        encounter.failure_reason = ""

        result = FirstEncounter.Result()
        result.result = encounter

        goal_handle.succeed()

        return result


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockFirstEncounterServer()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
