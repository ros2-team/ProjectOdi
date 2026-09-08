
import base64
import json
import os
import re
import time
import threading

from datetime import datetime
from pathlib import Path
from typing import Literal, cast

import cv2
import numpy as np
from geometry_msgs.msg import PoseStamped
from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose

from openai import OpenAI
from openai.types.responses import ResponseInputParam

import rclpy
from rclpy.action import (
    ActionClient,
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage

from odi_interfaces.action import ObserveObject
from odi_interfaces.msg import (
    ObservationResult,
    SemanticLabel,
    DetectedObject,
)
from odi_interfaces.srv import SaveObservation

ImageDetail = Literal[
    'auto',
    'low',
    'high',
    'original',
]

class ObservationCanceledError(RuntimeError):
    pass
class ObservationNode(Node):

    ANALYSIS_PROMPT = """
You are the detailed observation module of an exploration robot.

Analyze the object shown in the supplied image.
Use the first encounter information only as a hint.

First encounter information:
{encounter_context}

Return exactly one JSON object with this schema:

{{
  "object_name": "",
  "object_primary_color": "",
  "object_secondary_color": "",
  "object_material": "",
  "object_shape": "",
  "object_condition": "",
  "object_special_features": [],
  "diary_summary": ""
}}

Rules:
- Use concise lowercase English values for object properties.
- Write diary_summary in Korean using one or two factual sentences.
- Describe only visible properties.
- Do not invent hidden properties or functions.
- Use "unknown" when a property cannot be determined.
- object_special_features must be a JSON array.
- Do not include Markdown fences.
- Do not include explanations outside the JSON object.
""".strip()

    def __init__(self) -> None:
        super().__init__('observation_node')

        self.callback_group = ReentrantCallbackGroup()
        self.goal_lock = threading.Lock()
        self.goal_reserved = False

        self.locator_lock = threading.Lock()
        self.locator_event = threading.Event()

        self.frame_condition = threading.Condition()
        self.latest_image_bytes = None
        self.latest_image_sequence = 0

        self.awaiting_locator_result = False
        self.latest_approach_goal = None


        self.declare_parameter(
            'world_memory_timeout_sec',
            5.0,
        )
        self.declare_parameter(
            'openai_timeout_sec',
            30.0,
        )
        self.declare_parameter(
            'locator_timeout_sec',
            5.0,
        )
        self.declare_parameter(
            'navigation_server_timeout_sec',
            5.0,
        )
        self.declare_parameter(
            'navigation_timeout_sec',
            120.0,
        )
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
        self.declare_parameter('capture_settle_sec', 0.5)
        self.declare_parameter('capture_frame_count', 8)
        self.declare_parameter('capture_timeout_sec', 3.0)
        self.declare_parameter('capture_jpeg_quality', 95)


        openai_timeout_sec = (
            self.get_parameter('openai_timeout_sec')
            .get_parameter_value()
            .double_value
        )
        self.world_memory_timeout_sec = (
            self.get_parameter('world_memory_timeout_sec')
            .get_parameter_value()
            .double_value
        )
        self.locator_timeout_sec = (
            self.get_parameter('locator_timeout_sec')
            .get_parameter_value()
            .double_value
        )
        self.navigation_server_timeout_sec = (
            self.get_parameter(
                'navigation_server_timeout_sec'
            )
            .get_parameter_value()
            .double_value
        )
        self.navigation_timeout_sec = (
            self.get_parameter(
                'navigation_timeout_sec'
            )
            .get_parameter_value()
            .double_value
        )
        self.camera_topic = str(
            self.get_parameter('camera_topic').value
        )
        self.capture_settle_sec = float(
            self.get_parameter('capture_settle_sec').value
        )
        self.capture_frame_count = max(
            1,
            int(self.get_parameter('capture_frame_count').value),
        )
        self.capture_timeout_sec = float(
            self.get_parameter('capture_timeout_sec').value
        )
        self.capture_jpeg_quality = min(
            100,
            max(
                1,
                int(self.get_parameter('capture_jpeg_quality').value),
            ),
        )

        dataset_dir = Path(
            str(self.get_parameter('dataset_dir').value)
        ).expanduser()
        self.observation_image_dir = dataset_dir / 'observation'
        self.observation_image_dir.mkdir(
            parents=True,
            exist_ok=True,
        )



        self.model = os.getenv(
            'ODI_OPENAI_OBSERVATION_MODEL',
            os.getenv(
                'ODI_OPENAI_MODEL',
                'gpt-5.6-luna',
            ),
        )

        image_detail_value = os.getenv(
            'ODI_OPENAI_IMAGE_DETAIL',
            'high',
        ).lower()

        if image_detail_value in {
            'low',
            'high',
            'original',
            'auto',
        }:
            self.image_detail = cast(
                ImageDetail,
                image_detail_value,
            )

        else:
            self.get_logger().warning(
                'Invalid ODI_OPENAI_IMAGE_DETAIL : using high'
            )
            self.image_detail = 'high'

        api_key = os.getenv(
            'OPENAI_API_KEY',
            '',
        ).strip()

        self.openai_client = None

        if api_key:
            self.openai_client = OpenAI(
                api_key = api_key,
                timeout = openai_timeout_sec,
                max_retries=1,
            )
        else:
            self.get_logger().error(
                '\n OPENAI_API_KEY is missing'
                '\n Observation goals will be rejected'
            )



        self.save_observation_client = (
            self.create_client(
                SaveObservation,
                '/world_memory/save_observation',
                callback_group = self.callback_group,
            )
        )
        self.locator_request_publisher = (
            self.create_publisher(
                DetectedObject,
                '/observe/locate_request',
                10,
            )
        )
        self.approach_goal_subscription = (
            self.create_subscription(
                PoseStamped,
                '/observe/approach_goal',
                self.approach_goal_callback,
                10,
                callback_group = self.callback_group,
            )
        )
        self.image_subscription = self.create_subscription(
            CompressedImage,
            self.camera_topic,
            self.image_callback,
            qos_profile_sensor_data,
            callback_group=self.callback_group,
        )
        self.navigation_client = ActionClient(
            self,
            NavigateToPose,
            '/navigate_to_pose',
            callback_group = self.callback_group,
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
            '\n Observation Action Server is running'
            f'\n model = {self.model}'
            f'\n camera_topic = {self.camera_topic}'
            f'\n image_dir = {self.observation_image_dir}'
        )

    def image_callback(self, message: CompressedImage) -> None:
        if not message.data:
            return

        with self.frame_condition:
            self.latest_image_bytes = bytes(message.data)
            self.latest_image_sequence += 1
            self.frame_condition.notify_all()

    def wait_for_fresh_frame(
        self,
        after_sequence: int,
        timeout_sec: float,
    ) -> tuple[int, bytes] | None:
        deadline = time.monotonic() + timeout_sec

        with self.frame_condition:
            while (
                rclpy.ok()
                and self.latest_image_sequence <= after_sequence
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self.frame_condition.wait(
                    timeout=min(remaining, 0.1)
                )

            if self.latest_image_bytes is None:
                return None

            return (
                self.latest_image_sequence,
                self.latest_image_bytes,
            )

    def capture_observation_image(
        self,
        goal_handle,
        detection_id: str,
    ) -> str:
        settle_deadline = (
            time.monotonic() + self.capture_settle_sec
        )
        while time.monotonic() < settle_deadline:
            if goal_handle.is_cancel_requested:
                raise ObservationCanceledError(
                    'Observation canceled before image capture'
                )
            time.sleep(0.05)

        with self.frame_condition:
            last_sequence = self.latest_image_sequence

        candidates = []
        capture_deadline = (
            time.monotonic() + self.capture_timeout_sec
        )

        while (
            len(candidates) < self.capture_frame_count
            and time.monotonic() < capture_deadline
        ):
            if goal_handle.is_cancel_requested:
                raise ObservationCanceledError(
                    'Observation canceled during image capture'
                )

            remaining = capture_deadline - time.monotonic()
            frame_result = self.wait_for_fresh_frame(
                last_sequence,
                min(max(remaining, 0.0), 0.5),
            )
            if frame_result is None:
                continue

            last_sequence, image_bytes = frame_result
            encoded = np.frombuffer(
                image_bytes,
                dtype=np.uint8,
            )
            frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if frame is None or frame.size == 0:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sharpness = float(
                cv2.Laplacian(gray, cv2.CV_64F).var()
            )
            brightness = float(gray.mean())
            exposure_weight = (
                1.0 if 30.0 <= brightness <= 225.0 else 0.25
            )
            quality_score = sharpness * exposure_weight
            candidates.append(
                (
                    quality_score,
                    sharpness,
                    brightness,
                    frame,
                )
            )

        if not candidates:
            raise RuntimeError(
                'No fresh camera frame was available after approach'
            )

        _, sharpness, brightness, best_frame = max(
            candidates,
            key=lambda candidate: candidate[0],
        )

        success, encoded_image = cv2.imencode(
            '.jpg',
            best_frame,
            [
                int(cv2.IMWRITE_JPEG_QUALITY),
                self.capture_jpeg_quality,
            ],
        )
        if not success:
            raise RuntimeError(
                'Failed to encode the observation image'
            )

        safe_detection_id = re.sub(
            r'[^A-Za-z0-9_.-]+',
            '_',
            detection_id,
        ).strip('_') or 'unknown'
        timestamp = datetime.now().strftime(
            '%Y%m%d_%H%M%S_%f'
        )
        image_path = self.observation_image_dir / (
            f'{timestamp}_{safe_detection_id}.jpg'
        )
        image_path.write_bytes(encoded_image.tobytes())

        height, width = best_frame.shape[:2]
        self.get_logger().info(
            '\n ::Observation image captured::'
            f'\n path = {image_path}'
            f'\n size = {width}x{height}'
            f'\n candidates = {len(candidates)}'
            f'\n sharpness = {sharpness:.2f}'
            f'\n brightness = {brightness:.2f}'
        )

        return str(image_path)

    def approach_goal_callback(
            self,
            message: PoseStamped,
    ) -> None:

        with self.locator_lock:
            if not self.awaiting_locator_result:
                return

            self.latest_approach_goal = message
            self.awaiting_locator_result = False
            self.locator_event.set()

        self.get_logger().info(
            '\n ::Approach goal received::'
            f'\n frame_id = {message.header.frame_id}'
            f'\n x = {message.pose.position.x:.2f}'
            f'\n y = {message.pose.position.y:.2f}'
            f'\n orientation_z = {message.pose.orientation.z:.3f}'
            f'\n orientation_w = {message.pose.orientation.w:.3f}'
        )

    def request_approach_goal(
            self,
            goal_handle,
            target: DetectedObject,
    ) -> PoseStamped:

        self.locator_event.clear()

        with self.locator_lock:
            self.latest_approach_goal = None
            self.awaiting_locator_result = True

        try:
            self.get_logger().info(
                '\n ::locator request published::'
                f'\n detection_id = {target.detection_id}'
                f'\n center_x = {target.center_x}'
                f'\n center_y = {target.center_y}'
                f'\n width = {target.width}'
            )
            self.locator_request_publisher.publish(
                target
            )
            deadline = (
                time.monotonic()
                + self.locator_timeout_sec
            )

            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                    raise ObservationCanceledError(
                        'Observation canceled while waiting for locator'
                    )
                if self.locator_event.wait(0.05):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        'Observation Locator response timed out'
                    )

            if not rclpy.ok():
                raise RuntimeError(
                    'ROS shutdown while waiting for Observation locator'
                )

            with self.locator_lock:
                approach_goal = self.latest_approach_goal

            if approach_goal is None:
                raise RuntimeError(
                    'Observation locator returned no approach goal'
                )
            return approach_goal

        finally:
            with self.locator_lock:
                self.awaiting_locator_result = False

    def cancel_navigation_goal(
            self,
            navigation_goal_handle,
    ) -> None:

        cancel_future = navigation_goal_handle.cancel_goal_async()
        deadline = time.monotonic() + 3.0

        while(
            rclpy.ok()
            and not cancel_future.done()
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)

        self.get_logger().info(
            'Navigation cancellation requested'
        )

    def navigate_to_approach_goal(
        self,
        observation_goal_handle,
        approach_goal: PoseStamped,
    ) -> None:

        server_ready = (
            self.navigation_client.wait_for_server(
                timeout_sec=(
                    self.navigation_server_timeout_sec
                )
            )
        )

        if not server_ready:
            raise RuntimeError(
                'NavigateToPose action server is unavailable'
            )

        navigation_goal = NavigateToPose.Goal()
        navigation_goal.pose = approach_goal

        navigation_goal.pose.header.stamp = (
            self.get_clock().now().to_msg()
        )

        self.get_logger().info(
            '\n::Navigation goal requested::'
            f'\nframe_id = '
            f'{navigation_goal.pose.header.frame_id}'
            f'\nx = '
            f'{navigation_goal.pose.pose.position.x:.2f}'
            f'\ny = '
            f'{navigation_goal.pose.pose.position.y:.2f}'
        )

        send_goal_future = (
            self.navigation_client.send_goal_async(
                navigation_goal
            )
        )

        send_deadline = time.monotonic() + 10.0

        while (
            rclpy.ok()
            and not send_goal_future.done()
        ):
            if time.monotonic() >= send_deadline:
                raise RuntimeError(
                    'NavigateToPose goal response timed out'
                )

            time.sleep(0.05)

        if not send_goal_future.done():
            raise RuntimeError(
                'ROS shutdown while sending navigation goal'
            )

        navigation_goal_handle = (
            send_goal_future.result()
        )

        if (
            navigation_goal_handle is None
            or not navigation_goal_handle.accepted
        ):
            raise RuntimeError(
                'NavigateToPose goal was rejected'
            )

        self.get_logger().info(
            'NavigateToPose goal accepted'
        )

        if observation_goal_handle.is_cancel_requested:
            self.cancel_navigation_goal(
                navigation_goal_handle
            )
            raise ObservationCanceledError(
                'Observation canceled before navigation'
            )

        result_future = (
            navigation_goal_handle.get_result_async()
        )

        navigation_deadline = (
            time.monotonic()
            + self.navigation_timeout_sec
        )

        while (
            rclpy.ok()
            and not result_future.done()
        ):
            if (
                observation_goal_handle
                .is_cancel_requested
            ):
                self.cancel_navigation_goal(
                    navigation_goal_handle
                )
                raise ObservationCanceledError(
                    'Observation canceled during navigation'
                )

            if time.monotonic() >= navigation_deadline:
                self.cancel_navigation_goal(
                    navigation_goal_handle
                )
                raise RuntimeError(
                    'NavigateToPose navigation timed out'
                )

            time.sleep(0.05)

        if not result_future.done():
            raise RuntimeError(
                'ROS shutdown while waiting for navigation'
            )

        navigation_result = result_future.result()

        if navigation_result is None:
            raise RuntimeError(
                'NavigateToPose returned no result'
            )

        if (
            navigation_result.status
            != GoalStatus.STATUS_SUCCEEDED
        ):
            raise RuntimeError(
                'NavigateToPose failed: '
                f'status={navigation_result.status}'
            )

        self.get_logger().info(
            'NavigateToPose completed successfully'
        )


    def goal_callback(
            self,
            goal_request: ObserveObject.Goal
    ) -> GoalResponse:

        session_id = goal_request.session_id.strip()
        target = goal_request.target
        encounter = goal_request.encounter


        if self.openai_client is None:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n OPENAI_API_KEY is unavailable'
            )
            return GoalResponse.REJECT

        if not session_id:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n session_id is empty'
            )
            return GoalResponse.REJECT

        if not target.detection_id.strip():
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n target detection_id is empty'
            )
            return GoalResponse.REJECT

        if target.width <= 0 or target.height <= 0:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n target bounding box is invalid'
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

        if target.detection_id != encounter.detection_id:
            self.get_logger().warning(
                '\n ::Observation goal rejected::'
                '\n detection_id of target and encounter do not match'
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
            '\n ::Observation goal received::'
            f'\n session_id = {session_id}'
            f'\n detection_id = {encounter.detection_id}'
            f'\n class_name = {target.class_name}'
            f'\n center = {target.center_x}, {target.center_y}'
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

            self.publish_feedback(
                goal_handle,
                'LOCATING',
                0.35,
                'Calculating the object approach position',
            )

            approach_goal = self.request_approach_goal(
                goal_handle,
                request.target,
            )

            self.get_logger().info(
                '\n ::Object location calculated::'
                f'\n goal_x = {approach_goal.pose.position.x:.2f}'
                f'\n goal_y = {approach_goal.pose.position.y:.2f}'
            )

            self.publish_feedback(
                goal_handle,
                'APPROACHING',
                0.50,
                'Moving to the object approach position',
            )

            self.navigate_to_approach_goal(
                goal_handle,
                approach_goal,
            )

            self.get_logger().info(
                '\n ::Object approach completed::'
                f'\n goal_x = {approach_goal.pose.position.x:.2f}'
                f'\n goal_y = {approach_goal.pose.position.y:.2f}'
            )

            self.publish_feedback(
                goal_handle,
                'CAPTURING',
                0.65,
                'Capturing a clear image after approach',
            )

            observation_image_path = (
                self.capture_observation_image(
                    goal_handle,
                    encounter.detection_id,
                )
            )

            self.publish_feedback(
                goal_handle,
                'ANALYZING',
                0.75,
                'Analyzing the object with OpenAI vision',
            )

            analysis_data, raw_json = (
                self.analyze_image(
                    encounter,
                    observation_image_path,
                )
            )

            if goal_handle.is_cancel_requested:
                return self.finish_canceled_goal(
                    goal_handle,
                    encounter.detection_id,
                    started_at,
                )

            observation = self.build_observation(
                encounter,
                started_at,
                analysis_data,
                raw_json,
                observation_image_path,
            )

            self.publish_feedback(
                goal_handle,
                'SAVING',
                0.90,
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

        except ObservationCanceledError as error:
            self.get_logger().info(
                f'\n Observation canceled : {error}'
            )
            return self.finish_canceled_goal(
                goal_handle,
                encounter.detection_id,
                started_at,
            )

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
            analysis_data: dict,
            raw_json: str,
            observation_image_path: str,
    ) -> ObservationResult:

        observation = ObservationResult()
        observation.detection_id = encounter.detection_id
        observation.success = True
        observation.image_paths = [
            encounter.image_path,
            observation_image_path,
        ]
        observation.representative_image_path = (
            observation_image_path
        )

        detailed_label = self.build_label(
            analysis_data,
            raw_json,
            encounter.label,
        )
        observation.detailed_label = detailed_label

        diary_summary = str(
            analysis_data.get(
                'diary_summary',
                '',
            )
        ).strip()
        if not diary_summary:
            diary_summary = self.build_diary_summary(
                detailed_label
            )

        observation.diary_summary = diary_summary
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

        deadline = (
            time.monotonic()
            + self.world_memory_timeout_sec
        )
        while rclpy.ok() and not future.done():
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    'SaveObservation response timed out'
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
        self.navigation_client.destroy()
        self.action_server.destroy()
        super().destroy_node()


    def analyze_image(
            self,
            encounter,
            observation_image_path: str,
    ) -> tuple[dict,str]:

        image_path = Path(
            observation_image_path
        ).expanduser()
        if not image_path.is_file():
            raise RuntimeError(
                f'\n Observation image does not exist : {image_path}'
            )

        image_bytes = image_path.read_bytes()
        if not image_bytes:
            raise RuntimeError(
                '\n Observation image is empty'
            )

        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        label = encounter.label

        encounter_context = {
            'detection_id' : encounter.detection_id,
            'object_name' : label.object_name,
            'primary_color' : label.object_primary_color,
            'secondary_color' : label.object_secondary_color,
            'material' : label.object_material,
            'shape' : label.object_shape,
            'condition' : label.object_condition,
            'special_features' : list(label.object_special_features),
        }

        prompt = self.ANALYSIS_PROMPT.format(
            encounter_context = json.dumps(
                encounter_context,
                ensure_ascii = False,
            )
        )

        client = self.openai_client
        if client is None:
            raise RuntimeError(
                'OpenAI client is not initialized'
            )

        response_input = cast(
            ResponseInputParam,
            [
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
        )
        response = client.responses.create(
            model = self.model,
            input = response_input,
            max_output_tokens= 1000,
            store = False,
        )

        raw_json = (
            response.output_text or ''
        ).strip()

        if not raw_json:
            raise RuntimeError(
                'OpenAI returned an empty response'
            )

        analysis_data = self.parse_json_object(
            raw_json
        )

        usage = getattr(response, 'usage', None)
        if usage is not None:
            self.get_logger().info(
                '\n :: OpenAI usage ::'
                f'\n input = {getattr(usage, "input_tokens", 0)}'
                f'\n output = {getattr(usage, "output_tokens", 0)}'
            )

        return analysis_data, raw_json

    @staticmethod
    def build_label(
        analysis_data: dict,
        raw_json: str,
        fallback_label,
    ) -> SemanticLabel:
        label = SemanticLabel()

        label.object_name = (
            ObservationNode.read_string(
                analysis_data,
                'object_name',
                fallback_label.object_name,
            )
        )

        label.object_primary_color = (
            ObservationNode.read_string(
                analysis_data,
                'object_primary_color',
                fallback_label.object_primary_color,
            )
        )

        label.object_secondary_color = (
            ObservationNode.read_string(
                analysis_data,
                'object_secondary_color',
                fallback_label.object_secondary_color,
            )
        )

        label.object_material = (
            ObservationNode.read_string(
                analysis_data,
                'object_material',
                fallback_label.object_material,
            )
        )

        label.object_shape = (
            ObservationNode.read_string(
                analysis_data,
                'object_shape',
                fallback_label.object_shape,
            )
        )

        label.object_condition = (
            ObservationNode.read_string(
                analysis_data,
                'object_condition',
                fallback_label.object_condition,
            )
        )

        special_features = analysis_data.get(
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
            label.object_special_features = list(
                fallback_label.object_special_features
            )

        label.raw_json = raw_json

        return label

    @staticmethod
    def read_string(
        data: dict,
        key: str,
        fallback: str,
    ) -> str:
        value = data.get(key)
        normalized = str(value or '').strip().lower()

        if normalized not in {
            '',
            'unknown',
        }:
            return normalized

        fallback_value = str(fallback or '').strip().lower()

        if fallback_value:
            return fallback_value

        return 'unknown'

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
            cleaned = re.sub(
                r'\s*```$',
                '',
                cleaned,
            )

        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')

        if (
            first_brace < 0
            or last_brace < first_brace
        ):
            raise ValueError(
                'OpenAI response does not contain JSON.'
            )

        parsed = json.loads(
            cleaned[first_brace:last_brace + 1]
        )

        if not isinstance(parsed, dict):
            raise ValueError(
                'OpenAI JSON response is not an object.'
            )

        return parsed


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















