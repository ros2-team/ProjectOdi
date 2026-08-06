#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from cv_bridge import CvBridge
import cv2
from google import genai
from google.genai import types
import os
from datetime import datetime
import json

class GeminiVisionNode(Node):
    def __init__(self):
        super().__init__('gemini_vision_node')

        # 제미나이 API 키 셋업 (구글 AI 스튜디오에서 발급받은 키 입력)
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        # 이미지 yolo노드에서 받아오기
        self.subscription = self.create_subscription(CompressedImage, '/vla/trigger_image/compressed', self.image_callback, 10)
        
        self.bridge = CvBridge()
        
        # API 호출 중복 방지 플래그 (최초 1회만 호출하도록 제한)
        self.api_called = False

        # 데이터셋 저장하기 위한 경로 지정 
        package_root = os.path.dirname(os.path.dirname(__file__))

        self.declare_parameter("dataset_dir", "/home/kim/ProjectOdi/Odi_ws/src/perception/dataset")
        self.dataset_dir = self.get_parameter("dataset_dir").value

        # self.dataset_dir = os.path.join(package_root, "dataset")  # 26/8/5 경로 지정 문제로 주석

        self.image_dir = os.path.join(self.dataset_dir, "images")
        self.scene_dir = os.path.join(self.dataset_dir, "scenes")
        os.makedirs(self.image_dir, exist_ok=True)
        os.makedirs(self.scene_dir, exist_ok=True)


        # 제미니 프롬프트 지정
        self.prompt = "이 로봇 카메라에 포착된 상황을 분석해서, 현재 앞에 있는 객체나 상황을 한국어로 엄청 세밀하고 디테일하게 글자수 상관없이 분석해줘"

        self.get_logger().info('vla 입니다 ^^')

    def image_callback(self, msg):
        
        self.get_logger().info('VLA 트리거 감지! 이미지 수신 완료. Gemini 모델 분석 시작...')
        
        # 1. ROS CompressedImage 메시지를 OpenCV 이미지로 변환
        frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")
        
        # 2. OpenCV 이미지를 JPEG 바이트(Bytes) 배열로 인코딩
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success:
            self.get_logger().error('이미지 인코딩에 실패했습니다.')
            return
        
        image_bytes = encoded_image.tobytes()

        try:
            # 3. 최신 google-genai SDK를 이용한 멀티모달 콘텐츠 생성 요청
            # 텍스트와 이미지 바이트를 동시에 리스트로 전달합니다.
            response = self.client.models.generate_content(
                model='gemini-3.6-flash',
                contents=[
                    types.Part.from_bytes(
                        data = image_bytes,
                        mime_type = 'image/jpeg',
                    ), 
                    self.prompt
                ]
            )
            
            # 4. 결과 텍스트 터미널 출력
            print("\n" + "="*40)
            print(f"🤖 [Gemini VLA 분석 결과]: {response.text.strip()}")
            print("="*40 + "\n")
            
        except Exception as e:
            self.get_logger().error(f"Gemini API 호출 중 오류 발생: {str(e)}")

        self.save_dataset(frame, response.text)

    def save_dataset(self, frame, response):
            # 파일 이름 생성
        file_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        image_name = f"{file_id}.jpg"
        json_name = f"{file_id}.json"

        # 저장 경로 생성
        image_path = os.path.join(self.image_dir, image_name)
        scene_path = os.path.join(self.scene_dir, json_name)

        # 이미지 저장
        cv2.imwrite(image_path, frame)

        # JSON 생성
        scenedata = {
            "image": image_name,
            "prompt": self.prompt,
            "response": response,
            "timestamp": file_id
        }

        # JSON 저장
        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(scenedata, f, ensure_ascii=False, indent=4)

        self.get_logger().info(f"Dataset Saved : {image_name}")

def main():
    rclpy.init()
    node = GeminiVisionNode()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()