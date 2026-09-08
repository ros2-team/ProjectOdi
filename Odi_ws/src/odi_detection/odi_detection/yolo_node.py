"""YOLO detector publishing updates and mission-scoped detection batches."""

import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from ultralytics import YOLO

from odi_interfaces.msg import DetectedObject, DetectedObjectArray, MissionState


class YoloNode(Node):
    """Publish object updates and retry detection batches during exploration."""

    def __init__(self) -> None:
        super().__init__('yolo_node')

        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('confidence', 0.5)
        self.declare_parameter('process_every_n_frames', 3)
        self.declare_parameter('lost_frame_threshold', 30)
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('batch_publish_interval_sec', 1.0)

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
        self.mission_state = message.state

    def image_callback(self, message: CompressedImage) -> None:
        """Run inference and publish individual and batched detections."""
        self.frame_count += 1
        if self.frame_count % self.process_every_n_frames != 0:
            return

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

        for index, box in enumerate(result.boxes):
            coordinates = box.xyxy[0].cpu().numpy().astype(int)
            x1, y1, x2, y2 = map(int, coordinates)

            detection = DetectedObject()
            class_id = int(box.cls[0])
            detection.detection_id = (
                f'{self.current_session_id}:'
                f'{self.detection_episode}_{index}_{class_id}'
            )
            detection.class_name = self.model.names[class_id]
            detection.confidence = float(box.conf[0])
            detection.center_x = int((x1 + x2) / 2)
            detection.center_y = int((y1 + y2) / 2)
            detection.width = x2 - x1
            detection.height = y2 - y1

            detections.append(detection)
            crop_candidates.append(
                (detection.confidence, x1, y1, x2, y2)
            )
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
