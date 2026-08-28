
import json
import os

from openai import OpenAI

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

        #openAI api
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            self.get_logger().error(
                "OPENAI_API_KEY environment variable is missing"
            )
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is missing"
            )

        self.openai_model = os.getenv(
            "ODI_OPENAI_MODEL",
            "gpt-5.6-luna",
        )
        self.openai_client = OpenAI(
            api_key = api_key,
        )
        self.get_logger().info(
            f"OpenAI diary model : {self.openai_model}"
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

        try:
            diary_text = self.generate_diary_with_openai(
                get_response.observations
            )
        except Exception as error:
            return self.finish_failed_goal(
                goal_handle,
                f"OpenAI diary generation failed : {error}"
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
        save_request.model_name = self.openai_model

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

    def build_observation_data(
        self,
        stored_observations,
    ):
        observation_data = []

        for stored_observation in stored_observations:
            observation = stored_observation.observation

            if not observation.success:
                continue

            label = observation.detailed_label

            observation_data.append(
                {
                    'object_name' : label.object_name,
                    'primary_color' : label.object_primary_color,
                    'secondary_color' : label.object_secondary_color,
                    'material' : label.object_material,
                    'shape' : label.object_shape,
                    'condition' : label.object_condition,
                    'special_features' : list(
                        label.object_special_features
                    ),
                    'observation_summary' : observation.diary_summary,
                }
            )
        return observation_data

    def generate_diary_with_openai(
        self,
        stored_observations,
    ):
        observation_data = self.build_observation_data(
            stored_observations
        )

        if not observation_data:
            raise RuntimeError(
                "No successful observations were available"
            )
        observation_json = json.dumps(
            observation_data,
            ensure_ascii = False,
            indent = 2,
        )

        instructions = (
            "너는 귀여운 탐험 로봇 오디다."
            "탐험 중 관찰한 기록을 바탕으로 오디의 시점에서 한국어 탐험 일기를 작성한다."
            "제공된 관찰 사실만 사용하고 없는 사실은 만들지 않는다."
            "따뜻하고 호기심 많은 말투로 3~6 문장을 작성한다."
            "객체 ID, 데이터베이스, JSON, 인공지능 같은 기술 용어는 일기에 넣지 않는다."
            "제목이나 목록 없이 일기 본문만 반환한다."
        )

        user_input = (
            "다음은 이번 탐험에서 수집한 관찰 기록이다.\n\n"
            f"{observation_json}\n\n"
            "이 기록을 자연스럽게 연결해서 하나의 일기로 작성해줘."
        )

        response = self.openai_client.responses.create(
            model = self.openai_model,
            reasoning = {
                'effort': 'low',
            },
            instructions = instructions,
            input = user_input,
            max_output_tokens = 2000,
        )
        diary_text = response.output_text.strip()

        if not diary_text:
            raise RuntimeError(
                "OpenAI returned an empty diary"
            )

        return diary_text


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
