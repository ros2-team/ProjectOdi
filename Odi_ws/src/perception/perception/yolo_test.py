import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool
from cv_bridge import CvBridge
import cv2
from ultralytics import YOLO

class YoloTestNode(Node):
    def __init__(self):
        super().__init__('yolo_test_node')
        self.bridge = CvBridge()
        # CPU 쌩쌩하게 돌기 위해 Nano 모델 필수
        self.model = YOLO('yolov8n.pt') 
        
        # 1. 기존 RQT 확인용 퍼블리셔 (박스 쳐진 화면, 10 FPS)
        self.image_pub = self.create_publisher(CompressedImage, '/yolo/image/compressed', 1)
        
        # 2. VLA(Gemini) 전송용 특수 퍼블리셔 (원본 화면, 이벤트 발생 시 1장만 쏨)
        self.vlm_pub = self.create_publisher(CompressedImage, '/vla/trigger_image/compressed', 10)

        # 3. 객체 인식이 되면 자동 탐사 패키지에 상태 값 publish -> 자동 탐사 정지 / 재개 기능
        self.explore_pub = self.create_publisher(Bool, "explore/resume", 10)
        
        # 라즈베리파이 카메라 구독
        self.image_sub = self.create_subscription(CompressedImage, '/camera/image_raw/compressed', self.image_callback, 1)
        
        # 성능 다이어트용 카운터
        self.frame_count = 0
        
        # 💡 상태 머신(State Machine) 변수들
        self.is_vla_triggered = False  # Gemini에게 이미지를 쐈는지 기억하는 '자물쇠'
        self.lost_count = 0            # 객체가 시야에서 사라진 시간(프레임) 카운터
        
        self.get_logger().info('YOLO Detector with VLA Trigger Pipeline Started!')

    def image_callback(self, msg):
        
        # 네트워크 30FPS -> 연산 10FPS 다이어트
        self.frame_count += 1

        if self.frame_count % 3 != 0:
            return 

        # 압축 풀기
        frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")
        # YOLO 추론
        results = self.model(frame, conf=0.5, verbose=False, device='cpu', imgsz = 480)
        # 객체 인식 여부 확인 (사람(class 0)이 1명이라도 있는지)
        object_detected = len(results[0].boxes) > 0

        # ==========================================
        # 기존 RQT 렌더링용 퍼블리시 (박스 및 중심점)
        # ==========================================
        annotated_frame = results[0].plot()
        for box in results[0].boxes:
            coords = box.xyxy[0].cpu().numpy().astype(int)

            x1 = int(coords[0])
            y1 = int(coords[1])
            x2 = int(coords[2])
            y2 = int(coords[3])

            cx = int((x1 + x2) / 2)
            cy = int((y1 + y2) / 2)

            cv2.circle(annotated_frame, (cx, cy), 5, (0, 0, 255), -1)

            xyxy = [x1, x2, y1, y2]

        self.image_pub.publish(self.bridge.cv2_to_compressed_imgmsg(annotated_frame, dst_format="jpg"))
        
        # [핵심 로직] 상태 머신 (VLA 트리거 제어)
        if object_detected:
            self.lost_count = 0  # 객체가 시야에 있으니 상실 카운터 초기화
            
            # 자물쇠가 풀려있다면 (이번 타임에 처음 발견한 거라면!)
            if not self.is_vla_triggered:
                self.get_logger().info('🔥 목표물 최초 인식! VLA(Gemini) 노드로 사진 1장을 전송합니다.')
                
                # 주의: VLA 모델에게는 바운딩 박스가 그려진 사진보다 '원본(frame)'을 보내는 게 환각(Hallucination) 방지와 텍스트 묘사에 훨씬 유리.

                # 함수 호출
                self.crop_vlm_pub(frame, xyxy)

                # 자동 탐사 상태 주머니 만들기
                msg = Bool()
                Bool.data = False
                self.explore_pub.publish(msg)

                # 사진을 쐈으니 자물쇠를 잠금 (다시 안 쏘도록)
                self.is_vla_triggered = True 
            else:
                pass

        else:
            self.lost_count += 1
            
            # 객체가 시야에서 사라지고 30프레임(약 3초)이 지났다면?
            # -> 완전히 지나갔다고 판단하고, 다음 인식을 위해 자물쇠를 풂
            if self.is_vla_triggered and self.lost_count > 30:
                self.get_logger().info('🔄 목표물 상실 3초 경과. VLA 트리거 상태를 리셋(대기)합니다.')
                # self.is_vla_triggered = False

        # 욜로 이미지 크롭 후 pub
    def crop_vlm_pub(self, data, xyxy):
        # 바운딩 박스 xy 좌표 언패킹
        x1, x2, y1, y2 = xyxy
        frame = data

        # 이미지 자르기
        crop_frame = frame[y1:y2, x1:x2]

        # 자른 이미지로 보내기
        vlm_msg = self.bridge.cv2_to_compressed_imgmsg(crop_frame, dst_format="jpg")
        self.vlm_pub.publish(vlm_msg)

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
