#!/usr/bin/env python3

import base64
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import rclpy
from openai import OpenAI
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage

from odi_interfaces.action import FirstEncounter
from odi_interfaces.msg import EncounterResult, SemanticLabel


class FirstEncounterNode(Node):

    ANALYSIS_PROMPT = """
You are the first visual encounter module of an exploration robot.
Analyze only the main object in the supplied cropped image.
The detector's class hint is: {class_hint}

Return exactly one JSON object with this schema:
{{
  "object_name": "",
  "object_primary_color": "",
  "object_secondary_color": "",
  "object_material": "",
  "object_shape": "",
  "object_condition": "",
  "object_special_features": []
}}

Rules:
- Use concise lowercase English values.
- Treat the detector class as a hint, not as guaranteed truth.
- Use "unknown" when the image does not support a reliable answer.
- Use "none" for a secondary color only when no second color is visible.
- Do not invent hidden properties.
- object_special_features must be a JSON array of short strings.
- Do not include Markdown fences or any explanation outside the JSON object.
""".strip()

    def __init__(self) -> None:
        super().__init__('first_encounter_node')

        self.callback_group = ReentrantCallbackGroup()
        self.frame_lock = threading.Lock()
        self.goal_lock = threading.Lock()

        self.latest_image_bytes = None
        self.latest_image_received_ns = None
        self.goal_reserved = False

        self.declare_parameter(
            'camera_topic',
            '/camera/image_raw/compressed',
        )
        self.declare_parameter(
            'dataset_dir',
            os.getenv(
                'ODI_DATASET_DIR',
                str(Path.home() / 'ProjectOdi_data'),
            ),
        )
        self.declare_parameter('bbox_padding_ratio', 0.15)
        self.declare_parameter('max_image_dimension', 1024)
        self.declare_parameter('max_image_age_sec', 3.0)
        self.declare_parameter('openai_timeout_sec', 30.0)

        self.camera_topic = self.get_parameter(
            'camera_topic'
        ).value
        self.bbox_padding_ratio = float(
            self.get_parameter('bbox_padding_ratio').value
        )
        self.max_image_dimension = int(
            self.get_parameter('max_image_dimension').value
        )
        self.max_image_age_sec = float(
            self.get_parameter('max_image_age_sec').value
        )
        openai_timeout_sec = float(
            self.get_parameter('openai_timeout_sec').value
        )

        dataset_dir = Path(
            self.get_parameter('dataset_dir').value
        ).expanduser()
        self.image_dir = dataset_dir / 'first_encounter'
        self.image_dir.mkdir(parents=True, exist_ok=True)

        self.model = os.getenv(
            'ODI_OPENAI_FIRST_ENCOUNTER_MODEL',
            os.getenv('ODI_OPENAI_MODEL', 'gpt-5.6-luna'),
        )
        self.image_detail = os.getenv(
            'ODI_OPENAI_IMAGE_DETAIL',
            'high',
        ).lower()
        if self.image_detail not in {
            'low',
            'high',
            'original',
            'auto',
        }:
            self.get_logger().warning(
                'Invalid ODI_OPENAI_IMAGE_DETAIL; using high.'
            )
            self.image_detail = 'high'

        api_key = os.getenv('OPENAI_API_KEY', '').strip()
        self.openai_client = None
        if api_key:
            self.openai_client = OpenAI(
                api_key=api_key,
                timeout=openai_timeout_sec,
                max_retries=1,
            )
        else:
            self.get_logger().error(
                'OPENAI_API_KEY is missing. '
                'FirstEncounter goals will be rejected.'
            )

        self.image_subscription = self.create_subscription(
            CompressedImage,
            self.camera_topic,
            self.image_callback,
            qos_profile_sensor_data,
            callback_group=self.callback_group,
        )

        self.action_server = ActionServer(
            self,
            FirstEncounter,
            '/first_encounter',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )

        self.get_logger().info(
            'FirstEncounter Action Server is running\n'
            f'model = {self.model}\n'
            f'camera_topic = {self.camera_topic}\n'
            f'image_dir = {self.image_dir}'
        )

    def image_callback(self, message: CompressedImage) -> None:
        if not message.data:
            return

        with self.frame_lock:
            self.latest_image_bytes = bytes(message.data)
            self.latest_image_received_ns = (
                self.get_clock().now().nanoseconds
            )

    def goal_callback(
        self,
        goal_request: FirstEncounter.Goal,
    ) -> GoalResponse:
        target = goal_request.target

        if self.openai_client is None:
            self.get_logger().warning(
                'FirstEncounter goal rejected: '
                'OPENAI_API_KEY is unavailable.'
            )
            return GoalResponse.REJECT

        if not target.detection_id.strip():
            self.get_logger().warning(
                'FirstEncounter goal rejected: '
                'detection_id is empty.'
            )
            return GoalResponse.REJECT

        if target.width <= 0 or target.height <= 0:
            self.get_logger().warning(
                'FirstEncounter goal rejected: '
                'bounding box is invalid.'
            )
            return GoalResponse.REJECT

        with self.goal_lock:
            if self.goal_reserved:
                self.get_logger().warning(
                    'FirstEncounter goal rejected: '
                    'another goal is active.'
                )
                return GoalResponse.REJECT
            self.goal_reserved = True

        self.get_logger().info(
            '::FirstEncounter goal received::\n'
            f'detection_id = {target.detection_id}\n'
            f'class_name = {target.class_name}'
        )
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle) -> CancelResponse:
        self.get_logger().info(
            'FirstEncounter cancel requested: '
            f'{goal_handle.request.target.detection_id}'
        )
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle) -> FirstEncounter.Result:
        target = goal_handle.request.target
        started_at = self.get_clock().now().to_msg()
        image_path = ''

        try:
            self.publish_feedback(
                goal_handle,
                'CAPTURING',
                0.20,
                'Capturing the first encounter image.',
            )

            if goal_handle.is_cancel_requested:
                return self.finish_canceled_goal(
                    goal_handle,
                    target.detection_id,
                    started_at,
                    image_path,
                )

            frame = self.get_latest_frame()
            crop = self.crop_target(frame, target)
            crop = self.resize_for_analysis(crop)
            image_path, image_bytes = self.save_image(
                crop,
                target.detection_id,
            )

            self.publish_feedback(
                goal_handle,
                'ANALYZING',
                0.60,
                'Analyzing the object with OpenAI vision.',
            )

            scene_data, raw_json = self.analyze_image(
                image_bytes,
                target.class_name,
            )

            if goal_handle.is_cancel_requested:
                return self.finish_canceled_goal(
                    goal_handle,
                    target.detection_id,
                    started_at,
                    image_path,
                )

            self.publish_feedback(
                goal_handle,
                'COMPLETING',
                0.90,
                'Building the first encounter result.',
            )

            encounter = EncounterResult()
            encounter.detection_id = target.detection_id
            encounter.success = True
            encounter.image_path = image_path
            encounter.label = self.build_label(
                scene_data,
                raw_json,
            )
            encounter.started_at = started_at
            encounter.completed_at = (
                self.get_clock().now().to_msg()
            )
            encounter.failure_reason = ''

            result = FirstEncounter.Result()
            result.result = encounter

            goal_handle.succeed()
            self.get_logger().info(
                '::FirstEncounter completed::\n'
                f'detection_id = {encounter.detection_id}\n'
                f'object_name = {encounter.label.object_name}\n'
                f'image_path = {encounter.image_path}'
            )
            return result

        except Exception as error:
            self.get_logger().error(
                f'FirstEncounter failed: {error}'
            )
            return self.finish_aborted_goal(
                goal_handle,
                target.detection_id,
                started_at,
                image_path,
                str(error),
            )

        finally:
            with self.goal_lock:
                self.goal_reserved = False

    def get_latest_frame(self):
        with self.frame_lock:
            image_bytes = self.latest_image_bytes
            received_ns = self.latest_image_received_ns

        if image_bytes is None or received_ns is None:
            raise RuntimeError('No camera image has been received.')

        age_sec = (
            self.get_clock().now().nanoseconds - received_ns
        ) / 1e9
        if age_sec > self.max_image_age_sec:
            raise RuntimeError(
                f'The latest camera image is stale: {age_sec:.2f}s.'
            )

        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError('Failed to decode the camera image.')

        return frame

    def crop_target(self, frame, target):
        frame_height, frame_width = frame.shape[:2]

        padding_x = int(
            target.width * self.bbox_padding_ratio
        )
        padding_y = int(
            target.height * self.bbox_padding_ratio
        )

        x1 = max(
            0,
            int(target.center_x - target.width / 2) - padding_x,
        )
        y1 = max(
            0,
            int(target.center_y - target.height / 2) - padding_y,
        )
        x2 = min(
            frame_width,
            int(target.center_x + target.width / 2) + padding_x,
        )
        y2 = min(
            frame_height,
            int(target.center_y + target.height / 2) + padding_y,
        )

        if x2 <= x1 or y2 <= y1:
            raise RuntimeError(
                'The target bounding box is outside the camera image.'
            )

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            raise RuntimeError('The target crop is empty.')

        return crop

    def resize_for_analysis(self, image):
        height, width = image.shape[:2]
        largest_dimension = max(height, width)

        if largest_dimension <= self.max_image_dimension:
            return image

        scale = self.max_image_dimension / largest_dimension
        resized_width = max(1, int(width * scale))
        resized_height = max(1, int(height * scale))

        return cv2.resize(
            image,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )

    def save_image(
        self,
        image,
        detection_id: str,
    ) -> tuple[str, bytes]:
        success, encoded = cv2.imencode(
            '.jpg',
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), 90],
        )
        if not success:
            raise RuntimeError('Failed to encode the encounter image.')

        safe_detection_id = re.sub(
            r'[^A-Za-z0-9_.-]+',
            '_',
            detection_id,
        ).strip('_') or 'unknown'
        timestamp = datetime.now().strftime(
            '%Y%m%d_%H%M%S_%f'
        )
        image_path = self.image_dir / (
            f'{timestamp}_{safe_detection_id}.jpg'
        )
        image_bytes = encoded.tobytes()
        image_path.write_bytes(image_bytes)

        return str(image_path), image_bytes

    def analyze_image(
        self,
        image_bytes: bytes,
        class_hint: str,
    ) -> tuple[dict, str]:
        image_base64 = base64.b64encode(
            image_bytes
        ).decode('utf-8')
        prompt = self.ANALYSIS_PROMPT.format(
            class_hint=class_hint or 'unknown'
        )

        response = self.openai_client.responses.create(
            model=self.model,
            input=[
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'input_text',
                            'text': prompt,
                        },
                        {
                            'type': 'input_image',
                            'image_url': (
                                'data:image/jpeg;base64,'
                                f'{image_base64}'
                            ),
                            'detail': self.image_detail,
                        },
                    ],
                },
            ],
            max_output_tokens=800,
            store=False,
        )

        raw_json = response.output_text.strip()
        if not raw_json:
            raise RuntimeError('OpenAI returned an empty response.')

        scene_data = self.parse_json_object(raw_json)

        usage = getattr(response, 'usage', None)
        if usage is not None:
            self.get_logger().info(
                'OpenAI usage: '
                f'input={getattr(usage, "input_tokens", 0)}, '
                f'output={getattr(usage, "output_tokens", 0)}'
            )

        return scene_data, raw_json

    @staticmethod
    def parse_json_object(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith('```'):
            cleaned = re.sub(
                r'^```(?:json)?\s*',
                '',
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r'\s*```$', '', cleaned)

        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        if first_brace < 0 or last_brace < first_brace:
            raise ValueError('OpenAI response does not contain JSON.')

        parsed = json.loads(
            cleaned[first_brace:last_brace + 1]
        )
        if not isinstance(parsed, dict):
            raise ValueError('OpenAI JSON response is not an object.')

        return parsed

    @staticmethod
    def build_label(
        scene_data: dict,
        raw_json: str,
    ) -> SemanticLabel:
        label = SemanticLabel()
        label.object_name = FirstEncounterNode.read_string(
            scene_data,
            'object_name',
        )
        label.object_primary_color = (
            FirstEncounterNode.read_string(
                scene_data,
                'object_primary_color',
            )
        )
        label.object_secondary_color = (
            FirstEncounterNode.read_string(
                scene_data,
                'object_secondary_color',
            )
        )
        label.object_material = FirstEncounterNode.read_string(
            scene_data,
            'object_material',
        )
        label.object_shape = FirstEncounterNode.read_string(
            scene_data,
            'object_shape',
        )
        label.object_condition = FirstEncounterNode.read_string(
            scene_data,
            'object_condition',
        )

        special_features = scene_data.get(
            'object_special_features',
            [],
        )
        if isinstance(special_features, list):
            label.object_special_features = [
                str(feature).strip().lower()
                for feature in special_features
                if str(feature).strip()
            ][:10]
        else:
            label.object_special_features = []

        label.raw_json = raw_json
        return label

    @staticmethod
    def read_string(data: dict, key: str) -> str:
        value = data.get(key, 'unknown')
        if value is None:
            return 'unknown'
        normalized = str(value).strip().lower()
        return normalized or 'unknown'

    @staticmethod
    def publish_feedback(
        goal_handle,
        stage: str,
        progress: float,
        message: str,
    ) -> None:
        feedback = FirstEncounter.Feedback()
        feedback.stage = stage
        feedback.progress = progress
        feedback.message = message
        goal_handle.publish_feedback(feedback)

    def finish_canceled_goal(
        self,
        goal_handle,
        detection_id: str,
        started_at,
        image_path: str,
    ) -> FirstEncounter.Result:
        goal_handle.canceled()
        return self.build_failure_result(
            detection_id,
            started_at,
            image_path,
            'First encounter canceled.',
        )

    def finish_aborted_goal(
        self,
        goal_handle,
        detection_id: str,
        started_at,
        image_path: str,
        failure_reason: str,
    ) -> FirstEncounter.Result:
        goal_handle.abort()
        return self.build_failure_result(
            detection_id,
            started_at,
            image_path,
            failure_reason,
        )

    def build_failure_result(
        self,
        detection_id: str,
        started_at,
        image_path: str,
        failure_reason: str,
    ) -> FirstEncounter.Result:
        encounter = EncounterResult()
        encounter.detection_id = detection_id
        encounter.success = False
        encounter.image_path = image_path
        encounter.label = SemanticLabel()
        encounter.started_at = started_at
        encounter.completed_at = self.get_clock().now().to_msg()
        encounter.failure_reason = failure_reason

        result = FirstEncounter.Result()
        result.result = encounter
        return result

    def destroy_node(self) -> None:
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = FirstEncounterNode()
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


if __name__ == '__main__':
    main()
