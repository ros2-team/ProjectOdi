#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from odi_interfaces.msg import SemanticLabel
from cv_bridge import CvBridge
from google.genai import types
from google import genai
from datetime import datetime
import cv2
import os
import json

class GeminiVisionNode(Node):
    def __init__(self):
        super().__init__('gemini_vision_node')

        # 제미나이 API 키 셋업 (구글 AI 스튜디오에서 발급받은 키 입력)
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        ##################################################### sub ######################################################
        # 이미지 yolo노드에서 받아오기
        self.subscription = self.create_subscription(CompressedImage, '/vla/trigger_image/compressed', self.image_callback, 10)


        ##################################################### pub ##########################################################
        # 메세지 타입 퍼블리쉬
        self.scene_publisher = self.create_publisher(SemanticLabel, '/perception/scene_data_1st', 10)

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


        # 제미니 첫번째 프롬프트 지정
        self.first_prompt = """
                            당신은 탐사 로봇의 시각 인지 모듈입니다.

                            입력된 이미지를 분석하여 아래 JSON 형식으로만 응답하세요.

                            {
                                "object_name": "",
                                "primary_color": "",
                                "secondary_color": "",
                                "material": "",
                                "shape": "",
                                "condition": ""
                            }

                            규칙

                            - object_name
                            물체의 대표 이름을 영어 소문자로 작성합니다.
                            예시: bottle, chair, box, person, laptop, backpack

                            - primary_color
                            가장 눈에 띄는 색상을 영어 소문자로 작성합니다.
                            예시: red, blue, black, white

                            - secondary_color
                            두 번째로 많이 보이는 색상입니다.
                            없다면 "none"을 작성합니다.

                            - material
                            추정되는 재질을 영어 소문자로 작성합니다.
                            예시:
                            plastic
                            metal
                            wood
                            fabric
                            glass
                            paper
                            rubber

                            - shape
                            대표적인 형태를 영어 소문자로 작성합니다.
                            예시:
                            rectangle
                            cylinder
                            sphere
                            cube
                            irregular

                            - condition
                            물체의 현재 상태를 영어 소문자로 작성합니다.

                            가능한 값:
                            New
                            NORMAL
                            OLD
                            DIRTY
                            DAMAGED

                            반드시 JSON만 출력하세요.
                            Markdown이나 설명은 절대 출력하지 마세요.
                            """

        # 제미니 두번째 프롬프트 지정
        self.second_prompt = "이 로봇 카메라에 포착된 상황을 분석해서, 현재 앞에 있는 객체나 상황을 한국어로 엄청 세밀하고 디테일하게 글자수 상관없이 분석해줘"

        # 제미니 모델
        self.model = 'gemini-3.5-flash-lite'
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
                model = self.model,
                contents=[
                    types.Part.from_bytes(
                        data = image_bytes,
                        mime_type = 'image/jpeg',
                    ), 
                    self.first_prompt
                ]
            )
            if response:
                self.save_dataset(frame, response.text)
                self.get_logger().info("데이터 저장 완료 !!!!")
            
            # 4. 결과 텍스트 터미널 출력
            print("\n" + "="*40)
            print(f"🤖 [Gemini VLA 분석 결과]: {response.text.strip()}")
            print("="*40 + "\n")
            
        except Exception as e:
            self.get_logger().error(f"Gemini API 호출 중 오류 발생: {str(e)}")

        

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
        # Gemini 응답(JSON 문자열)을 dict로 변환
        scene_data = json.loads(response)

        msg = SemanticLabel()
        msg.object_name = scene_data.get("object_name", "")
        msg.object_primary_color = scene_data.get("primary_color", "")
        msg.object_secondary_color = scene_data.get("secondary_color", "")
        msg.object_material = scene_data.get("material", "")
        msg.object_shape = scene_data.get("shape", "")
        msg.object_condition = scene_data.get("condition", "")

        # 추가 정보 저장
        scene_data["image"] = image_name
        scene_data["timestamp"] = file_id
        scene_data["prompt"] = "first_prompt"

        # JSON 저장
        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(scene_data, f, ensure_ascii=False, indent=4)

        self.get_logger().info(f"Dataset Saved : {image_name}")

        self.publish(msg)

    def publish(self, msg):
        self.scene_publisher.publish(msg)
        self.get_logger().info("성공적으로 보냈다 ^^")

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