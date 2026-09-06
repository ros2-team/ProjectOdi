import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool
from cv_bridge import CvBridge
import cv2
from ultralytics import YOLO

# coordinator / object_locator 와 같은 타입이어야 한다.
from odi_interfaces.msg import DetectedObject


class YoloTestNode(Node):
    """
    YOLO 노드의 역할은 두 가지뿐이다.

      1) 볼 가치가 있는 것만 발행한다      -> /yolo/detection
      2) coordinator 가 "찍어" 하면 crop 을 보낸다

    언제 찍을지는 이 노드가 정하지 않는다. observe_coordinator 가 정한다.
    """

    def __init__(self):
        super().__init__('yolo_test_node')
        self.bridge = CvBridge()

        # CPU 쌩쌩하게 돌기 위해 Nano 모델 필수
        self.model = YOLO('yolov8n.pt')

        # ==================================================================
        #  여기만 만지면 된다
        # ==================================================================

        # 배경으로 취급할 class. 여기 있는 건 아예 발행하지 않는다.
        #
        # 화이트리스트가 아니라 블랙리스트인 이유:
        #   "새로운 걸 발견하는 로봇" 이라서, 목록에 없는 물건이
        #   영원히 안 잡히면 컨셉이 깨진다. 가구·사람만 배경으로 빼고
        #   나머지는 전부 통과시킨다.
        #
        # 돌려보면서 계속 추가할 것. 파인튜닝으로 class 늘리면 여기도 갱신.
        self.ignore_classes = {
            'chair', 'couch', 'bed', 'bench', 'dining table',
            'tv', 'refrigerator', 'microwave', 'oven', 'sink', 'toilet', 'person'
        }

        # y필터: bbox 아랫변이 이 값보다 위(작은 값)면 버린다.
        # None 이면 끈다. 지금은 꺼져 있음.
        self.min_bottom_y = None

        # 같은 class 가 몇 프레임 연속 보여야 발행할지. 1 이면 끈다.
        # 임계 근처에서 깜빡거리면 3 으로 올려라.
        self.confirm_frames = 3

        # 1차에서 찍은 class 를 기억했다가 2차에도 같은 class 만 찍는다.
        # 사람 찍고 가서 의자 찍는 사고를 막는다.
        self.lock_target_class = True

        # ==================================================================

        self.frame_skip = 3         # 네트워크 30FPS -> 연산 10FPS
        self.conf = 0.6
        self.min_crop_px = 10
        self.stale_warn_sec = 3.0

        # ====================== publisher ======================
        self.image_pub = self.create_publisher(CompressedImage, '/yolo/image/compressed', 1)
        self.detection_pub = self.create_publisher(DetectedObject, '/yolo/detection', 10)
        self.vlm_1st_pub = self.create_publisher(CompressedImage, '/vla/trigger_image_1st/compressed', 10)
        self.vlm_2nd_pub = self.create_publisher(CompressedImage, '/vla/trigger_image_2nd/compressed', 10)

        # ※ /explore/resume 은 여기서 발행하지 않는다. coordinator 담당이다.

        # ====================== subscriber ======================
        self.create_subscription(CompressedImage, '/camera/image_raw/compressed',self.image_callback, 1)
        self.create_subscription(Bool, '/observe/capture_1st', self.capture_1st_cb, 10)
        self.create_subscription(Bool, '/observe/capture_2nd', self.capture_2nd_cb, 10)

        # ====================== 상태 ======================
        self.frame_count = 0

        # 원본 프레임과 통과한 박스 목록을 들고만 있는다.
        # crop 은 촬영 신호가 올 때 그 자리에서 만든다.
        # (매 프레임 jpg 인코딩하는 낭비를 없애려는 것도 있다)
        self.latest_frame = None
        self.latest_dets = []
        self.latest_time = None

        self.last_top_class = None
        self.stable_count = 0

        self.locked_class = None    # 1차에서 잡힌 target

        self.get_logger().info(
            'YOLO Detector 시작. 무시 class %d개, 촬영 트리거 대기 중.'
            % len(self.ignore_classes))

    # ==================== 메인 루프 ====================

    def image_callback(self, msg):
        self.frame_count += 1
        if self.frame_count % self.frame_skip != 0:
            return

        frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")
        results = self.model(frame, conf=self.conf, verbose=False, device='cpu', imgsz = 320)

        # ---- 박스를 dict 로 정리하면서 걸러낸다 ----
        all_dets = []
        for box in results[0].boxes:
            coords = box.xyxy[0].cpu().numpy().astype(int)
            x1 = int(coords[0])
            y1 = int(coords[1])
            x2 = int(coords[2])
            y2 = int(coords[3])

            class_id = int(box.cls[0])
            class_name = self.model.names[class_id]

            d = {
                'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
                'cx': (x1 + x2) // 2,
                'cy': (y1 + y2) // 2,
                'w': x2 - x1,
                'h': y2 - y1,
                'area': (x2 - x1) * (y2 - y1),
                'class_id': class_id,
                'class_name': class_name,
                'confidence': float(box.conf[0]),
            }

            # 1) class 블랙리스트 — 제일 싸니까 먼저
            d['keep'] = (class_name not in self.ignore_classes)

            # 2) y필터 — 꺼져 있으면 건너뛴다
            if d['keep'] and self.min_bottom_y is not None:
                d['keep'] = (y2 >= self.min_bottom_y)

            all_dets.append(d)

        dets = []
        for d in all_dets:
            if d['keep']:
                dets.append(d)

        # 큰 것(= 가까운 물체)을 맨 앞으로.
        # coordinator 는 IDLE 상태에서 먼저 도착한 것 하나만 잡으므로,
        # crop 대상(dets[0]) 과 먼저 발행되는 것이 같아야 한다.
        dets.sort(key=lambda d: d['area'], reverse=True)

        # 촬영 신호는 언제 올지 모르니 항상 최신으로 갱신해 둔다
        self.latest_frame = frame
        self.latest_dets = dets
        self.latest_time = self.get_clock().now()

        self.publish_detections(dets)
        self.publish_debug_image(results, all_dets)

    # ==================== 발행 ====================

    def publish_detections(self, dets):
        """통과한 것만, 큰 것부터 하나씩 보낸다."""
        top_class = dets[0]['class_name'] if len(dets) > 0 else None

        # 깜빡임 방지. confirm_frames 가 1 이면 사실상 통과.
        if top_class == self.last_top_class:
            self.stable_count += 1
        else:
            self.stable_count = 1
            self.last_top_class = top_class

        if top_class is None or self.stable_count < self.confirm_frames:
            return

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

    def publish_debug_image(self, results, all_dets):
        """
        rqt 확인용. 걸러진 것도 보여야 블랙리스트를 튜닝할 수 있다.
          빨간 점  = 통과 (발행됨)
          회색 점  = 걸러짐
        """
        annotated = results[0].plot()

        if self.min_bottom_y is not None:
            w = annotated.shape[1]
            cv2.line(annotated, (0, self.min_bottom_y),
                     (w, self.min_bottom_y), (0, 255, 255), 1)

        for d in all_dets:
            color = (0, 0, 255) if d['keep'] else (128, 128, 128)
            cv2.circle(annotated, (d['cx'], d['cy']), 5, color, -1)

        self.image_pub.publish(
            self.bridge.cv2_to_compressed_imgmsg(annotated, dst_format="jpg"))

    # ==================== 촬영 신호 ====================

    def capture_1st_cb(self, msg):
        self.locked_class = None    # 1차에서 target 을 새로 잡는다
        self.send_crop('1차')

    def capture_2nd_cb(self, msg):
        self.send_crop('2차')
        self.locked_class = None    # 사이클 종료

    def pick_det(self, stage):
        """어느 박스를 찍을지 고른다. 없으면 None."""
        if len(self.latest_dets) == 0:
            return None

        # 2차에서는 1차에 찍은 것과 같은 class 만 찍는다
        if self.lock_target_class and self.locked_class is not None:
            for d in self.latest_dets:
                if d['class_name'] == self.locked_class:
                    return d

            self.get_logger().warn(
                '%s: 1차에 찍은 %s 가 지금 화면에 없다 (현재 %s). '
                '다른 물체를 찍지 않고 건너뛴다.'
                % (stage, self.locked_class,
                   self.latest_dets[0]['class_name']))
            return None

        return self.latest_dets[0]

    def send_crop(self, stage):
        if self.latest_frame is None:
            self.get_logger().warn('%s 요청을 받았지만 프레임이 없다.' % stage)
            return

        det = self.pick_det(stage)
        if det is None:
            if len(self.latest_dets) == 0:
                self.get_logger().warn(
                    '%s 요청을 받았지만 볼 만한 물체가 없다.' % stage)
            return

        crop = self.make_crop(self.latest_frame, det)
        if crop is None:
            self.get_logger().warn('%s: crop 이 너무 작다. 보내지 않음.' % stage)
            return

        dt = self.get_clock().now() - self.latest_time
        age = dt.nanoseconds / 1e9

        # 도착했는데 물체가 화면에서 벗어나 있으면 옛날 프레임이 나간다.
        # 로그상으로는 정상이라 알아채기 어렵다.
        if age > self.stale_warn_sec:
            self.get_logger().warn(
                '%s 프레임이 %.1f초 전 것이다. 물체가 안 보이는 상태일 수 있음.'
                % (stage, age))

        if stage == '1차':
            self.vlm_1st_pub.publish(crop)
            if self.lock_target_class:
                self.locked_class = det['class_name']
        else:
            self.vlm_2nd_pub.publish(crop)

        self.get_logger().info(
            '%s 이미지 전송 (%s, %dx%d, 프레임 나이 %.2fs)'
            % (stage, det['class_name'], det['w'], det['h'], age))

    def make_crop(self, frame, det):
        """
        ※ 박스가 그려진 annotated 가 아니라 원본 frame 을 잘라야 한다.
          VLM 이 박스 선까지 물체의 일부로 묘사하는 걸 막기 위해서다.
        """
        h, w = frame.shape[:2]

        # 박스가 화면 밖으로 나가면 그대로 자를 때 빈 배열이 나온다
        x1 = max(0, det['x1'])
        y1 = max(0, det['y1'])
        x2 = min(w, det['x2'])
        y2 = min(h, det['y2'])

        if (x2 - x1) < self.min_crop_px or (y2 - y1) < self.min_crop_px:
            return None

        return self.bridge.cv2_to_compressed_imgmsg(
            frame[y1:y2, x1:x2], dst_format="jpg")


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