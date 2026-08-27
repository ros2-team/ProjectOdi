
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
from odi_interfaces.srv import (
    GetMissionObservations,
    SaveDiary,
)


class ReflectionNode(Node):

    def __init__(self) -> None:
        super().__init__("reflection_node")

        self.callback_group = ReentrantCallbackGroup()

        self.get_observations_client = self.create_client(
            GetMissionObservations,
            '/world_memory/get_mission_observations',
            callback_group = self.callback_group,
        )
        self.save_diary_client = self.create_client(
            SaveDiary,
            '/world_memory/save_diary',
            callback_group = self.callback_group,
        )

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

    async def execute_callback(
        self,
        goal_handle,
    ) -> Reflect.Result:
        session_id = (
            goal_handle.request.session_id.strip()
        )

        self.publish_feedback(
            goal_handle=goal_handle,
            stage='COLLECTING',
            progress=0.25,
            message='Collecting exploration records.',
        )

        if goal_handle.is_cancel_requested:
            return self.finish_canceled_goal(goal_handle)

        if not self.get_observations_client.wait_for_service(
            timeout_sec=3.0
        ):
            return self.finish_failed_goal(
                goal_handle,
                'GetMissionObservations service is unavailable.',
            )

        get_request = GetMissionObservations.Request()
        get_request.session_id = session_id

        try:
            get_response = await (
                self.get_observations_client.call_async(
                    get_request
                )
            )
        except Exception as error:
            return self.finish_failed_goal(
                goal_handle,
                f'Failed to request observations: {error}',
            )
        if get_response is None:
            return self.finish_failed_goal(
                goal_handle,
                "GetMissionObservations returned no response"
            )

        if not get_response.success:
            return self.finish_failed_goal(
                goal_handle,
                'Failed to load observations: '
                f'{get_response.message}',
            )

        if not get_response.observations:
            return self.finish_failed_goal(
                goal_handle,
                f'No observations found for session '
                f'{session_id}.',
            )

        if goal_handle.is_cancel_requested:
            return self.finish_canceled_goal(goal_handle)

        self.publish_feedback(
            goal_handle=goal_handle,
            stage='GENERATING',
            progress=0.60,
            message='Generating exploration diary.',
        )

        diary_text = self.generate_temporary_diary(
            get_response.observations
        )

        if not diary_text:
            return self.finish_failed_goal(
                goal_handle,
                'No successful observations were available.',
            )

        if goal_handle.is_cancel_requested:
            return self.finish_canceled_goal(goal_handle)

        self.publish_feedback(
            goal_handle=goal_handle,
            stage='SAVING',
            progress=0.85,
            message='Saving exploration diary.',
        )

        if not self.save_diary_client.wait_for_service(
            timeout_sec=3.0
        ):
            return self.finish_failed_goal(
                goal_handle,
                'SaveDiary service is unavailable.',
            )

        save_request = SaveDiary.Request()
        save_request.session_id = session_id
        save_request.diary_text = diary_text
        save_request.model_name = 'temporary_template_v1'

        try:
            save_response = await (
                self.save_diary_client.call_async(
                    save_request
                )
            )
        except Exception as error:
            return self.finish_failed_goal(
                goal_handle,
                f'Failed to save diary: {error}',
            )
        if save_response is None:
            return self.finish_failed_goal(
                goal_handle,
                "SaveDiary returned no response"
            )

        if not save_response.success:
            return self.finish_failed_goal(
                goal_handle,
                f'Diary save failed: {save_response.message}',
            )

        if goal_handle.is_cancel_requested:
            return self.finish_canceled_goal(goal_handle)

        result = Reflect.Result()
        result.success = True
        result.diary_id = save_response.diary_id
        result.diary_text = diary_text
        result.message = save_response.message

        goal_handle.succeed()

        self.get_logger().info(
            '::Reflection completed::\n'
            f'session_id = {session_id}\n'
            f'diary_id = {result.diary_id}\n'
            f'diary_text = {result.diary_text}'
        )

        return result

    def generate_temporary_diary(
        self,
        stored_observations,
    ) -> str:

        diary_entries = []

        for stored_observation in stored_observations:
            observation = stored_observation.observation

            if not observation.success:
                continue

            if observation.diary_summary.strip():
                diary_entries.append(
                    observation.diary_summary.strip()
                )
                continue

            label = observation.detailed_label

            object_name = (
                label.object_name.strip() or "이름을 알 수 없는 물체"
            )
            features = []

            if label.object_primary_color.strip():
                features.append(
                    label.object_primary_color.strip()
                )

            if label.object_material.strip():
                features.append(
                    label.object_material.strip()
                )

            if label.object_shape.strip():
                features.append(
                    label.object_shape.strip()
                )

            feature_text = ''.join(features)

            if feature_text:
                diary_entries.append(
                    f"{feature_text} 특징을 가진 {object_name}을 발견했다."
                )
            else:
                diary_entries.append(
                    f"{object_name}을 발견하고 가까이서 관찰했다."
                )

        if not diary_entries:
            return ''

        return(
            "오늘은 주변을 천천히 탐험하며 새로운 물체들을 관찰했다."
            "새로운 물체를 관찰했다"
            + " ".join(diary_entries)
            + "새로운 것들을 살펴볼 수 있어서"
            "흥미로운 탐험이었다."
        )

    def publish_feedback(
        self,
        goal_handle,
        stage: str,
        progress: float,
        message: str,
    ) -> None:
        feedback = Reflect.Feedback()
        feedback.stage = stage
        feedback.progress = progress
        feedback.message = message

        goal_handle.publish_feedback(feedback)

        self.get_logger().info(
            "\n :: Reflect feedback ::"
            f"\n stage = {stage}"
            f"\n progress = {progress:.2f}"
            f"\n message = {message}"
        )

    def finish_failed_goal(
        self,
        goal_handle,
        message: str,
    ) -> Reflect.Result:

        goal_handle.abort()

        result = Reflect.Result()
        result.success = False
        result.diary_id = ''
        result.diary_text = ''
        result.message = message

        self.get_logger().error(
            f"Reflection failed : {message}"
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
