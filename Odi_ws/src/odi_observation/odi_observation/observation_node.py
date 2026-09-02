
import threading
import time
from pathlib import Path

import rclpy

from rclpy.action import (
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from odi_interfaces.action import ObserveObject
from odi_interfaces.msg import ObservationResult
from odi_interfaces.srv import SaveObservation

class ObservationNode(Node):
    def __init__(self) -> None:
        super().__init__('observation_node')

        self.callback_group = ReentrantCallbackGroup()
        self.goal_lock = threading.Lock()
        self.goal_reserved = False

        self.declare_parameter(
            'world_memory_timeout_sec',
            5.0,
        )

        self.world_memory_timeout_sec = (
            self.get_parameter('world_memory_timeout_sec')
            .get_parameter_value()
            .double_value
        )

        self.save_observation_client = (
            self.create_client(
                SaveObservation,
                '/world_memory/save_observation',
                callback_group = self.callback_group,
            )
        )
        self.action_server = ActionServer(
            self,
            ObserveObject,
            '/observe_object',
            execute_callback = self.execute_callback,
            goal_callback = self.goal_callback,
            cancel_callback = self.cancel_callback,
            callback_group = self.callback_group,
        )

        self.get_logger().info(
            'Observation Action Server is running'
        )

    def goal_callback(
            self,
            goal_request: ObserveObject.Goal
    ) -> GoalResponse:

        session_id = goal_request.session_id.strip()
        encounter = goal_request.encounter

        if not session_id:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n session_id is empty'
            )
            return GoalResponse.REJECT

        if not encounter.success:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n FirstEncounter was not successful'
            )
            return GoalResponse.REJECT

        if not encounter.detection_id.strip():
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n detection_id is empty'
            )
            return GoalResponse.REJECT

        if not encounter.image_path.strip():
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n image_path is empty'
            )
            return GoalResponse.REJECT

        if not Path(encounter.image_path).is_file():
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n encounter image does not exist'
                f'\n image_path = {encounter.image_path}'
            )
            return GoalResponse.REJECT

        with self.goal_lock:
            if self.goal_reserved:
                self.get_logger().warning(
                    '\n ::Observation goal rejected::'
                    '\n another goal is active'
                )
                return GoalResponse.REJECT
            self.goal_reserved = True

        self.get_logger().info(
            '\n ::Observation goal recieved::'
            f'\n session_id = {session_id}'
            f'\n detection_id = {encounter.detection_id}'
            f'\n object_name = {encounter.label.object_name}'
        )

        return GoalResponse.ACCEPT

    def cancel_callback(
            self,
            goal_handle,
    ) -> CancelResponse:

        self.get_logger().info(
            '\n ::Observation cancel requested::'
            f'\n {goal_handle.request.encounter.detection_id}'
        )

        return CancelResponse.ACCEPT

    def execute_callback(
            self,
            goal_handle,
    ) -> ObserveObject.Result:

        request = goal_handle.request
        encounter = request.encounter
        started_at = self.get_clock().now().to_msg()

        try:
            self.publish_feedback(
                goal_handle,
                'PREPARING',
                0.20,
                'Preparing the observation result',
            )

            if goal_handle.is_cancel_requested:
                self.get_logger().warning(
                    '\n ::Observation canceled::'
                    '\n Observation canceled before DB save'
                )
                return self.finish_canceled_goal(
                    goal_handle,
                    encounter.detection_id,
                    started_at,
                )

            observation = self.build_observation(
                encounter,
                started_at,
            )
            self.publish_feedback(
                goal_handle,
                'SAVING',
                0.80,
                'Saving the observation to world memory',
            )

            memory_id = self.save_observation(
                goal_handle,
                request.session_id,
                observation,
            )

            if goal_handle.is_cancel_requested:
                self.get_logger().warning(
                    '\n ::Observation canceled::'
                    '\n Observation was canceled after DB save'
                )
                return self.finish_canceled_goal(
                    goal_handle,
                    encounter.detection_id,
                    started_at,
                )

            observation.saved_to_database = True
            observation.memory_id = memory_id
            observation.completed_at = self.get_clock().now().to_msg()

            result = ObserveObject.Result()
            result.result = observation

            goal_handle.succeed()

            self.get_logger().info(
                '\n ::Observation completed::'
                f'\n detection_id = {observation.detection_id}'
                f'\n memory_id = {memory_id}'
                f'\n diary_summary = {observation.diary_summary}'
            )

            return result

        except Exception as error:
            self.get_logger().error(
                f'\n Observation failed : {error}'
            )
            return self.finish_aborted_goal(
                goal_handle,
                encounter.detection_id,
                started_at,
                str(error),
            )

        finally:
            with self.goal_lock:
                self.goal_reserved = False

    def build_observation(
            self,
            encounter,
            started_at,
    ) -> ObservationResult:

        observation = ObservationResult()
        observation.detection_id = encounter.detection_id
        observation.success = True
        observation.image_paths = [
            encounter.image_path
        ]
        observation.representative_image_path = (
            encounter.image_path
        )
        observation.detailed_label = encounter.label
        observation.diary_summary = (
            self.build_diary_summary(
                encounter.label
            )
        )

        observation.saved_to_database = False
        observation.memory_id = ''
        observation.started_at = started_at
        observation.completed_at = self.get_clock().now().to_msg()
        observation.failure_reason = ''

        return observation

    def save_observation(
            self,
            goal_handle,
            session_id: str,
            observation: ObservationResult,
    ) -> str:

        service_ready = (
            self.save_observation_client.wait_for_service(
                timeout_sec = self.world_memory_timeout_sec
            )
        )
        if not service_ready:
            raise RuntimeError(
                'SaveObservation service is unavailable'
            )

        request = SaveObservation.Request()
        request.session_id = session_id
        request.observation = observation

        future = (
            self.save_observation_client.call_async(
                request
            )
        )

        while rclpy.ok() and not future.done():
            if goal_handle.is_cancel_requested:
                raise RuntimeError(
                    'Observation canceled while waiting DB'
                )
            time.sleep(0.05)

        if not future.done():
            raise RuntimeError(
                'ROS shutdown while waiting DB'
            )

        response = future.result()

        if response is None:
            raise RuntimeError(
                'SaveObservation returned no response'
            )
        if not response.success:
            raise RuntimeError(response.message)

        return response.memory_id

    def finish_canceled_goal(
            self,
            goal_handle,
            detection_id: str,
            started_at,
    ) -> ObserveObject.Result:

        goal_handle.canceled()

        return self.build_failure_result(
            detection_id,
            started_at,
            'Observation canceled',
        )

    def finish_aborted_goal(
            self,
            goal_handle,
            detection_id: str,
            started_at,
            failure_reason: str,
    ) -> ObserveObject.Result:

        goal_handle.abort()

        return self.build_failure_result(
            detection_id,
            started_at,
            failure_reason,
        )

    def build_failure_result(
            self,
            detection_id: str,
            started_at,
            failure_reason: str,
    ) ->ObserveObject.Result:

        observation = ObservationResult()

        observation.detection_id = detection_id
        observation.success = False
        observation.image_paths = []
        observation.representative_image_path = ''
        observation.diary_summary = ''
        observation.saved_to_database = False
        observation.memory_id = ''
        observation.started_at = started_at
        observation.completed_at = self.get_clock().now().to_msg()
        observation.failure_reason = failure_reason

        result = ObserveObject.Result()
        result.result = observation

        return result

    def destroy_node(self) -> None:
        self.action_server.destroy()
        super().destroy_node()

    @staticmethod
    def publish_feedback(
        goal_handle,
        stage: str,
        progress: float,
        message: str,
    ) -> None:

        feedback = ObserveObject.Feedback()
        feedback.stage = stage
        feedback.progress = progress
        feedback.message = message

        goal_handle.publish_feedback(feedback)

    @staticmethod
    def build_diary_summary(label) -> str:
        object_name = (
            label.object_name or 'unknown object'
        )
        primary_color = (
            label.object_primary_color or 'unknown'
        )
        material = (
            label.object_material or 'unknown'
        )
        condition = (
            label.object_condition or 'unknown'
        )

        return (
            f'{primary_color} 색상의 '
            f'{object_name}을 관찰했다. '
            f'재질은 {material}으로 보였고, '
            f'상태는 {condition}이었다.'
        )


def main(args=None) -> None:
    rclpy.init(args=args)

    node = ObservationNode()
    executor = MultiThreadedExecutor(
        num_threads=2
    )
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

if __name__ == '__main__':
    main()

















