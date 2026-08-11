#!/usr/bin/env python3

import rclpy
from rclpy.node import Node

from odi_interfaces.msg import CuriosityDecision
from odi_interfaces.srv import EvaluateCuriosity


class MockCuriosityServer(Node):

    def __init__(self) -> None:
        super().__init__("mock_curiosity_server")

        self.service = self.create_service(
            EvaluateCuriosity,
            "/evaluate_curiosity",
            self.evaluate_callback,
        )

        self.get_logger().info(
            "Mock Curiosity Server is Running."
        )

    def evaluate_callback(
        self,
        request,
        response,
    ):
        encounter = request.encounter

        self.get_logger().info(
            "::Curiosity evaluation requested::\n"
            f"detection_id = {encounter.detection_id}\n"
            f"object_name = "
            f"{encounter.label.object_name}"
        )

        decision = CuriosityDecision()

        decision.detection_id = (
            encounter.detection_id
        )

        decision.curiosity_score = 0.8
        decision.similarity_score = 0.3

        decision.action = "OBSERVE"
        decision.reason = (
            "Mock object contains novel features."
        )

        decision.novel_features = [
            "new color",
            "new shape",
        ]

        decision.duplicated_features = [
            "same object category",
        ]

        decision.compared_record_count = 3
        decision.evaluated_at = (
            self.get_clock().now().to_msg()
        )

        response.success = True
        response.decision = decision
        response.message = (
            "Curiosity evaluation completed."
        )

        return response


def main(args=None) -> None:
    rclpy.init(args=args)

    node = MockCuriosityServer()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
