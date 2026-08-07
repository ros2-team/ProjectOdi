import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
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
        
        # 2. 💡 VLA(Gemini) 전송용 특수 퍼블리셔 (원본 화면, 이벤트 발생 시 1장만 쏨)
        self.vla_pub = self.create_publisher(CompressedImage, '/vla/trigger_image/compressed', 10)
        
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

        # YOLO 추론 (imgsz=320 강제 축소로 CPU 방어)
        # results = self.model(frame, classes=[0], conf=0.5, verbose=False, device='cpu', imgsz=320)

        # YOLO 추론
        results = self.model(frame, conf=0.5, verbose=False, device='cpu')
        
        # 💡 객체 인식 여부 확인 (사람(class 0)이 1명이라도 있는지)
        object_detected = len(results[0].boxes) > 0
        
        # ==========================================
        # 🚀 [핵심 로직] 상태 머신 (VLA 트리거 제어)
        # ==========================================
        if object_detected:
            self.lost_count = 0  # 객체가 시야에 있으니 상실 카운터 초기화
            
            # 자물쇠가 풀려있다면 (이번 타임에 처음 발견한 거라면!)
            if not self.is_vla_triggered:
                self.get_logger().info('🔥 목표물 최초 인식! VLA(Gemini) 노드로 사진 1장을 전송합니다.')
                
                # 주의: VLA 모델에게는 바운딩 박스가 그려진 사진보다 '쌩얼(frame)'을 보내는 게
                # 환각(Hallucination) 방지와 텍스트 묘사에 훨씬 유리합니다.
                vla_msg = self.bridge.cv2_to_compressed_imgmsg(frame, dst_format="jpg")
                self.vla_pub.publish(vla_msg)
                
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

        # ==========================================
        # 🎨 기존 RQT 렌더링용 퍼블리시 (박스 및 중심점)
        # ==========================================
        annotated_frame = results[0].plot()
        for box in results[0].boxes:
            coords = box.xyxy[0].cpu().numpy().astype(int)
            cx = int((coords[0] + coords[2]) / 2)
            cy = int((coords[1] + coords[3]) / 2)
            cv2.circle(annotated_frame, (cx, cy), 5, (0, 0, 255), -1)
            
        self.image_pub.publish(self.bridge.cv2_to_compressed_imgmsg(annotated_frame, dst_format="jpg"))

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

############################## 8/5 여기는 욜로만 테스트 한거 #######################################
# #!/usr/bin/env python3

# import rclpy
# from rclpy.node import Node
# from sensor_msgs.msg import CompressedImage
# from std_msgs.msg import Bool
# from cv_bridge import CvBridge
# from ultralytics import YOLO
# import cv2


# class YoloDetector(Node):

#     def __init__(self):
#         super().__init__("yolo_detector")

#         self.bridge = CvBridge()

#         # YOLO 모델
#         self.model = YOLO("yolov8n.pt")

#         # Subscriber
#         self.image_sub = self.create_subscription(CompressedImage, "/camera/image_raw/compressed", self.image_callback, 1)

#         # Bounding Box 그려진 이미지
#         self.image_pub = self.create_publisher(CompressedImage, "/yolo/image/compressed", 1)

#         # yolo 객체 인식시 상태 토픽
#         self.yolo_status_pub = self.create_publisher(Bool, "/yolo/object_status")

#         # yolo 주기 컨트롤 용 변수 추가
#         self.frame_count = 0

#         self.get_logger().info("YOLO Detector Started")

#     def image_callback(self, msg):
        
#         self.frame_count += 1

#         if self.frame_count % 3 != 0:
#                     return 

#         frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")

#         results = self.model(frame, conf=0.5, verbose=False, device='cpu')

#         for result in results:

#             for box in result.boxes:

#                 coords = box.xyxy[0].cpu().numpy().astype(int)
#                 x1, y1, x2, y2 = coords

#                 cx = int((x1 + x2) / 2)
#                 cy = int((y1 + y2) / 2)

#                 cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)

#                 cv2.circle(frame, (int(cx), int(cy)), 5, (0, 0, 255), -1)

#         self.image_pub.publish(self.bridge.cv2_to_compressed_imgmsg(frame, dst_format = "jpg"))

# def main(args=None):

#     rclpy.init(args=args)

#     node = YoloDetector()

#     rclpy.spin(node)

#     node.destroy_node()
#     rclpy.shutdown()


# if __name__ == "__main__":
#     main()