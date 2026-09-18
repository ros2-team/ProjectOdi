"""YOLO detector publishing updates and mission-scoped detection batches."""

import time
import math

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, CameraInfo, LaserScan
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from rclpy.duration import Duration
from tf2_ros import Buffer, TransformListener
from ultralytics import YOLO

from odi_interfaces.msg import DetectedObject, DetectedObjectArray, MissionState, EncounterResult, ObservationResult
from odi_detection.candidate_policy import CandidatePolicy, projected_range
from odi_detection.turn_gate import TurnGate


class YoloNode(Node):
    """Publish object updates and retry detection batches during exploration."""

    def __init__(self) -> None:
        super().__init__('yolo_node')

        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('confidence', 0.35)
        self.declare_parameter('process_every_n_frames', 3)
        self.declare_parameter('lost_frame_threshold', 30)
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('batch_publish_interval_sec', 1.0)
        self.declare_parameter('minimum_box_area_ratio', 0.01)
        self.declare_parameter('minimum_detection_frames', 2)
        self.declare_parameter('reobserve_cooldown_sec', 90.0)
        self.declare_parameter('excluded_classes', ['tv', 'laptop', 'person', 'chair', 'refrigerator', 'bed'])
        self.declare_parameter('ignored_top_ratio', 0.10)
        self.declare_parameter('maximum_observation_distance', 2.0)
        self.declare_parameter('camera_info_topic', '/camera/camera_info')
        self.declare_parameter('label_identity_enabled', True)
        self.label_identity_enabled = bool(
            self.get_parameter('label_identity_enabled').value)
        # Identity association must not depend on pausing observation candidates.
        self.declare_parameter('turn_identity_enabled', True)
        self.turn_identity_enabled = bool(
            self.get_parameter('turn_identity_enabled').value)
        self.declare_parameter('recent_detection_guards_enabled', False)
        self.recent_detection_guards_enabled = bool(
            self.get_parameter('recent_detection_guards_enabled').value)
        self.policy = CandidatePolicy(
            min_area=float(self.get_parameter('minimum_box_area_ratio').value),
            min_hits=max(1, int(self.get_parameter('minimum_detection_frames').value)),
            cooldown=float(self.get_parameter('reobserve_cooldown_sec').value),
            excluded=self.get_parameter('excluded_classes').value,
            ignored_top_ratio=float(self.get_parameter('ignored_top_ratio').value),
        )
        self.maximum_observation_distance = float(
            self.get_parameter('maximum_observation_distance').value)
        self.declare_parameter('observation_turn_start_rad_s', 0.20)
        self.declare_parameter('observation_turn_stop_rad_s', 0.10)
        self.declare_parameter('observation_settle_sec', 0.5)
        self.turn_gate = TurnGate(
            start=float(self.get_parameter('observation_turn_start_rad_s').value),
            stop=float(self.get_parameter('observation_turn_stop_rad_s').value),
            settle=float(self.get_parameter('observation_settle_sec').value))
        self.camera_info = None
        self.scan = None
        self.scan_received = 0.0
        self.odom_pose = None
        self.odom_received = 0.0
        self.range_notice_at = -math.inf
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(CameraInfo,
            self.get_parameter('camera_info_topic').value,
            self.camera_info_callback, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.scan_callback, qos_profile_sensor_data)
        self.create_subscription(Odometry, '/odom', self.odom_callback, qos_profile_sensor_data)
        self.create_subscription(EncounterResult, '/first_encounter/result',
                                 self.encounter_callback, 10)
        self.create_subscription(ObservationResult, '/observation/result',
                                 self.observation_callback, 10)

        self.confidence = self.get_parameter('confidence').value
        self.process_every_n_frames = max(
            1,
            self.get_parameter('process_every_n_frames').value,
        )
        self.lost_frame_threshold = self.get_parameter(
            'lost_frame_threshold'
        ).value
        self.device = self.get_parameter('device').value
        self.batch_publish_interval_sec = max(
            0.1, float(self.get_parameter('batch_publish_interval_sec').value)
        )

        self.bridge = CvBridge()
        self.model = YOLO(self.get_parameter('model_path').value)

        self.image_publisher = self.create_publisher(
            CompressedImage,
            '/yolo/image/compressed',
            1,
        )
        self.vlm_publisher = self.create_publisher(
            CompressedImage,
            '/vla/trigger_image/compressed',
            10,
        )
        self.detection_publisher = self.create_publisher(
            DetectedObject,
            '/yolo/detection',
            10,
        )
        self.batch_publisher = self.create_publisher(
            DetectedObjectArray,
            '/perception/detected_objects',
            10,
        )

        self.image_subscription = self.create_subscription(
            CompressedImage,
            '/camera/image_raw/compressed',
            self.image_callback,
            1,
        )

        self.frame_count = 0
        self.detection_episode = 0
        self.episode_active = False
        self.lost_frame_count = 0
        self.current_session_id = ''
        self.mission_state = 'IDLE'
        self.last_batch_sent_at = None
        self.mission_subscription = self.create_subscription(
            MissionState, '/mission/state', self.mission_callback, 10,
        )

        self.get_logger().info(
            'YOLO detection pipeline is running'
        )

    def mission_callback(self, message: MissionState) -> None:
        """Rearm detection for each new mission, including visible targets."""
        if message.session_id != self.current_session_id:
            self.current_session_id = message.session_id
            self.detection_episode = 0
            self.episode_active = False
            self.lost_frame_count = 0
            self.last_batch_sent_at = None
            self.policy.reset(message.session_id)
        self.mission_state = message.state

    def camera_info_callback(self, message):
        self.camera_info = message

    def scan_callback(self, message):
        self.scan = message
        self.scan_received = time.monotonic()

    def odom_callback(self, message):
        position = message.pose.pose.position
        self.odom_pose = (position.x, position.y)
        self.odom_received = time.monotonic()
        self.turn_gate.update(message.twist.twist.angular.z, self.odom_received)

    def encounter_callback(self, message):
        # Suppress both successful and failed attempts to avoid retry loops.
        if message.detection_id.startswith(self.current_session_id + ':'):
            self.policy.handled(message.detection_id, time.monotonic())

    def observation_callback(self, message):
        if (message.success and self.current_session_id
                and message.detection_id.startswith(self.current_session_id + ':')):
            guarded = self.policy.observation_completed(
                message.detection_id, time.monotonic())
            if guarded:
                self.get_logger().info(
                    'Post-observation tracking guard active for up to 10s (2s lost timeout): '
                    + message.detection_id)

    def scan_points_in_camera(self, image_message, width, height):
        info, scan = self.camera_info, self.scan
        if info is None or scan is None or self.maximum_observation_distance <= 0:
            return []
        if (info.width != width or info.height != height or any(abs(d) > 1e-6 for d in info.d)
                or time.monotonic()-self.scan_received > 0.5):
            return []
        def seconds(stamp):
            return stamp.sec + stamp.nanosec*1e-9
        if abs(seconds(scan.header.stamp)-seconds(image_message.header.stamp)) > 0.25:
            return []
        try:
            tf = self.tf_buffer.lookup_transform(
                info.header.frame_id, scan.header.frame_id,
                Time.from_msg(scan.header.stamp), timeout=Duration(seconds=0.03)).transform
        except Exception:
            return []
        q, t = tf.rotation, tf.translation
        points = []
        for index, distance in enumerate(scan.ranges):
            if not math.isfinite(distance) or not scan.range_min <= distance <= scan.range_max:
                continue
            angle = scan.angle_min + index*scan.angle_increment
            x, y = distance*math.cos(angle), distance*math.sin(angle)
            # Quaternion rotation of (x, y, 0), then camera translation.
            ux, uy, uz = -2*q.z*y, 2*q.z*x, 2*(q.x*y-q.y*x)
            points.append((x+q.w*ux+q.y*uz-q.z*uy+t.x,
                           y+q.w*uy+q.z*ux-q.x*uz+t.y,
                           q.w*uz+q.x*uy-q.y*ux+t.z, distance))
        return points

    def image_callback(self, message: CompressedImage) -> None:
        """Run inference and publish individual and batched detections."""
        self.frame_count += 1
        if self.frame_count % self.process_every_n_frames != 0:
            return

        view_ready = (not self.recent_detection_guards_enabled
                      or self.turn_gate.allowed(time.monotonic()))
        frame = self.bridge.compressed_imgmsg_to_cv2(
            message,
            'bgr8',
        )
        results = self.model(
            frame,
            conf=self.confidence,
            verbose=False,
            device=self.device,
        )
        result = results[0]
        annotated_frame = result.plot()
        detections = []
        crop_candidates = []

        now = time.monotonic()
        height, width = frame.shape[:2]
        boxes = [tuple(map(int, box.xyxy[0].cpu().numpy().astype(int))) for box in result.boxes]
        names = [self.model.names[int(box.cls[0])] for box in result.boxes]
        pose = self.odom_pose if now-self.odom_received <= 1.0 else None
        associated = self.policy.update(list(zip(boxes, names)), width, height, now, pose,
                                        turn_link=(self.turn_identity_enabled
                                                   and self.turn_gate.can_link(now)),
                                        label_link=self.label_identity_enabled)
        if not view_ready:
            # Track identity keeps updating, but turning frames cannot establish stability.
            for track in self.policy.tracks.values():
                track['hits'] = 0
        associations = {(box, name): (key, eligible) for box, name, key, eligible in associated}
        scan_points = self.scan_points_in_camera(message, width, height)

        for index, box in enumerate(result.boxes):
            coordinates = box.xyxy[0].cpu().numpy().astype(int)
            x1, y1, x2, y2 = map(int, coordinates)

            detection = DetectedObject()
            class_id = int(box.cls[0])
            detection.detection_id, eligible = associations[(boxes[index], names[index])]
            detection.class_name = self.model.names[class_id]
            detection.confidence = float(box.conf[0])
            detection.center_x = int((x1 + x2) / 2)
            detection.center_y = int((y1 + y2) / 2)
            detection.width = x2 - x1
            detection.height = y2 - y1

            distance = projected_range(scan_points, boxes[index], self.camera_info.k) if scan_points else None
            if distance is not None and distance > self.maximum_observation_distance:
                eligible = False
            if eligible:
                detections.append(detection)
                crop_candidates.append((detection.confidence, x1, y1, x2, y2))
            # Apply the same view/class gate to normal-mode tracking updates.
            if self.policy.in_observation_view(boxes[index], names[index], height):
                self.detection_publisher.publish(detection)

            cv2.circle(
                annotated_frame,
                (detection.center_x, detection.center_y),
                5,
                (0, 0, 255),
                -1,
            )

        annotated_message = self.bridge.cv2_to_compressed_imgmsg(
            annotated_frame,
            dst_format='jpg',
        )
        annotated_message.header = message.header
        self.image_publisher.publish(annotated_message)

        # Keep the camera preview running while idle, without consuming the
        # first detection event before Behavior is ready to explore.
        if self.mission_state != 'EXPLORING' or not self.current_session_id:
            return

        if self.recent_detection_guards_enabled and (
                not view_ready or not self.turn_gate.allowed(time.monotonic())):
            for track in self.policy.tracks.values():
                track['hits'] = 0
            return

        if self.maximum_observation_distance > 0 and not scan_points and now-self.range_notice_at >= 30.0:
            self.range_notice_at = now
            self.get_logger().warning(
                'No calibrated synchronized scan projection; using visual candidate filters only')

        if detections:
            self.lost_frame_count = 0
            now = time.monotonic()
            if (
                self.last_batch_sent_at is None
                or now - self.last_batch_sent_at >= self.batch_publish_interval_sec
            ):
                self._publish_detection_batch(message, detections)
                if not self.episode_active:
                    self._publish_best_crop(frame, message, crop_candidates)
                self.episode_active = True
                self.last_batch_sent_at = now
            return

        self.lost_frame_count += 1
        if (
            self.episode_active
            and self.lost_frame_count > self.lost_frame_threshold
        ):
            self.episode_active = False
            self.detection_episode += 1
            self.last_batch_sent_at = None
            self.get_logger().info(
                'Detection episode reset after target loss'
            )

    def _publish_detection_batch(
        self,
        image_message: CompressedImage,
        detections: list[DetectedObject],
    ) -> None:
        """Publish current objects, retaining IDs when retrying an episode."""
        batch = DetectedObjectArray()
        batch.header = image_message.header
        batch.objects = detections
        self.batch_publisher.publish(batch)
        log = self.get_logger().debug if self.episode_active else self.get_logger().info
        log(f'Published detection batch: {len(detections)} object(s)')

    def _publish_best_crop(
        self,
        frame,
        image_message: CompressedImage,
        candidates: list[tuple[float, int, int, int, int]],
    ) -> None:
        """Publish the highest-confidence crop for legacy VLM consumers."""
        if not candidates:
            return

        _, x1, y1, x2, y2 = max(candidates)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return

        crop_message = self.bridge.cv2_to_compressed_imgmsg(
            crop,
            dst_format='jpg',
        )
        crop_message.header = image_message.header
        self.vlm_publisher.publish(crop_message)


def main(args=None) -> None:
    """Run the YOLO detector node."""
    rclpy.init(args=args)
    node = YoloNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
