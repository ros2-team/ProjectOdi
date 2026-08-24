import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool
from cv_bridge import CvBridge
import cv2
from ultralytics import YOLO

# coordinator / object_locator 와 같은 타입이어야 한다.
# 타입이 다르면 ROS2 는 에러 없이 그냥 연결을 안 한다.
# 여러 객체를 동시에 다뤄야 할 때 DetectedObjectArray 로 바꾼다.
from odi_interfaces.msg import DetectedObject


class YoloTestNode(Node):
    """
    YOLO 노드의 역할은 두 가지뿐이다.

      1) 매 프레임 무엇이 어디에 보이는지 발행한다  -> /yolo/detection
      2) coordinator 가 "찍어" 하면 그 순간의 crop 을 보낸다

    언제 찍을지는 이 노드가 정하지 않는다. observe_coordinator 가 정한다.
    """

    def __init__(self):
        super().__init__('yolo_test_node')
        self.bridge = CvBridge()

        # CPU 쌩쌩하게 돌기 위해 Nano 모델 필수
        self.model = YOLO('yolov8n.pt')

        # ================== 설정 값 ==================
        self.frame_skip = 3         # 네트워크 30FPS -> 연산 10FPS 다이어트
        self.conf = 0.5
        self.min_crop_px = 10       # 이보다 작은 crop 은 보낼 가치가 없다
        self.stale_warn_sec = 3.0   # crop 이 이보다 오래됐으면 경고
        # =============================================

        # ====================== publisher ======================
        # rqt 확인용 (박스 쳐진 화면). VLM 으로는 절대 안 나간다.
        self.image_pub = self.create_publisher(CompressedImage, '/yolo/image/compressed', 1)

        # 박스 하나당 메시지 하나. 큰 것부터 발행한다.
        self.detection_pub = self.create_publisher(DetectedObject, '/yolo/detection', 10)

        # VLM 전송용. 1차/2차를 나눠야 VLM 이 프롬프트를 구분할 수 있다.
        self.vlm_1st_pub = self.create_publisher(CompressedImage, '/vla/trigger_image_1st/compressed', 10)
        self.vlm_2nd_pub = self.create_publisher(CompressedImage, '/vla/trigger_image_2nd/compressed', 10)

        # ※ /explore/resume 은 여기서 발행하지 않는다. coordinator 담당이다.
        #   두 노드가 같이 쏘면 탐사가 껐다 켜졌다 한다.

        # ====================== subscriber ======================
        self.create_subscription(CompressedImage, '/camera/image_raw/compressed', self.image_callback, 1)

        self.create_subscription(Bool, '/observe/capture_1st', self.capture_1st_cb, 10)
        self.create_subscription(Bool, '/observe/capture_2nd', self.capture_2nd_cb, 10)

        # ====================== 상태 ======================
        self.frame_count = 0

        # 최신 crop 을 들고만 있는다. 발행은 신호가 올 때.
        self.latest_crop = None
        self.latest_crop_time = None
        self.latest_crop_name = ''

        self.get_logger().info('YOLO Detector 시작. 1차/2차 촬영 트리거 대기 중.')

    # ==================== 메인 루프 ====================

    def image_callback(self, msg):
        self.frame_count += 1
        if self.frame_count % self.frame_skip != 0:
            return

        frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")
        results = self.model(frame, conf=self.conf, verbose=False, device='cpu')
        boxes = results[0].boxes

        # 박스를 dict 리스트로 정리한다
        dets = []
        for box in boxes:
            coords = box.xyxy[0].cpu().numpy().astype(int)
            x1 = int(coords[0])
            y1 = int(coords[1])
            x2 = int(coords[2])
            y2 = int(coords[3])

            class_id = int(box.cls[0])

            dets.append({
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'cx': (x1 + x2) // 2,
                'cy': (y1 + y2) // 2,
                'w': x2 - x1,
                'h': y2 - y1,
                'area': (x2 - x1) * (y2 - y1),
                'class_id': class_id,
                'class_name': self.model.names[class_id],
                'confidence': float(box.conf[0]),
            })

        # ★ 면적 큰 것(= 가까운 물체)을 맨 앞으로.
        #
        #   메시지를 박스마다 하나씩 보내기 때문에, coordinator 는 IDLE 상태에서
        #   "먼저 도착한 것" 하나만 잡고 나머지는 무시한다.
        #   그래서 crop 대상(dets[0])과 먼저 발행되는 것이 같아야
        #   좌표와 사진이 서로 다른 물체를 가리키는 사고를 막을 수 있다.
        dets.sort(key=lambda d: d['area'], reverse=True)

        if len(dets) > 0:
            self.publish_detections(dets)
            self.update_crop(frame, dets[0])

        self.publish_debug_image(results, dets)

    # ==================== 발행 ====================

    def publish_detections(self, dets):
        """큰 것부터 하나씩 보낸다. 순서를 바꾸면 안 된다."""
        for d in dets:
            obj = DetectedObject()
            obj.detection_id = str(d['class_id'])
            obj.class_name = d['class_name']
            obj.confidence = d['confidence']
            obj.center_x = d['cx']
            obj.center_y = d['cy']
            obj.width = d['w']
            obj.height = d['h']
            self.detection_pub.publish(obj)

    def publish_debug_image(self, results, dets):
        """rqt 로 눈으로 보는 용도. 여기서 나가는 이미지는 VLM 으로 안 간다."""
        annotated = results[0].plot()
        for d in dets:
            cv2.circle(annotated, (d['cx'], d['cy']), 5, (0, 0, 255), -1)
        self.image_pub.publish(
            self.bridge.cv2_to_compressed_imgmsg(annotated, dst_format="jpg"))

    # ==================== crop 보관 ====================

    def update_crop(self, frame, det):
        """
        crop 을 만들어 들고만 있는다. 실제 발행은 촬영 신호가 올 때.
        매 프레임 갱신되므로 신호가 온 시점의 가장 최신 화면이 나간다.

        ※ 박스가 그려진 annotated 가 아니라 원본 frame 을 잘라야 한다.
          VLM 이 박스 선까지 물체의 일부로 묘사하는 걸 막기 위해서다.
        """
        h, w = frame.shape[:2]

        # 박스가 화면 밖으로 나가는 경우가 있다. 그대로 자르면 빈 배열이 나온다.
        x1 = max(0, det['x1'])
        y1 = max(0, det['y1'])
        x2 = min(w, det['x2'])
        y2 = min(h, det['y2'])

        if (x2 - x1) < self.min_crop_px or (y2 - y1) < self.min_crop_px:
            return   # 너무 작으면 갱신하지 않고 기존 crop 을 유지한다

        crop = frame[y1:y2, x1:x2]

        self.latest_crop = self.bridge.cv2_to_compressed_imgmsg(
            crop, dst_format="jpg")
        self.latest_crop_time = self.get_clock().now()
        self.latest_crop_name = det['class_name']

    # ==================== 촬영 신호 ====================

    def capture_1st_cb(self, msg):
        self.send_crop('1차')

    def capture_2nd_cb(self, msg):
        self.send_crop('2차')

    def send_crop(self, stage):
        if self.latest_crop is None:
            self.get_logger().warn(
                '%s 촬영 요청을 받았지만 crop 이 없다. 보내지 않음.' % stage)
            return

        dt = self.get_clock().now() - self.latest_crop_time
        age = dt.nanoseconds / 1e9

        # 도착했는데 물체가 화면에서 벗어나 있으면 아까 멀리서 찍은 사진이
        # 그대로 나간다. 로그상으로는 정상이라 알아채기 어렵다.
        if age > self.stale_warn_sec:
            self.get_logger().warn(
                '%s crop 이 %.1f초 전 것이다. 지금 물체가 안 보이는 상태일 수 있음.'
                % (stage, age))

        if stage == '1차':
            self.vlm_1st_pub.publish(self.latest_crop)
        else:
            self.vlm_2nd_pub.publish(self.latest_crop)

        self.get_logger().info(
            '%s 이미지 전송 (%s, crop 나이 %.2fs)'
            % (stage, self.latest_crop_name, age))


def main(args=None):
    rclpy.init(args=args)
    node = YoloTestNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()