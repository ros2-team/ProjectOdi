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
    """
    촬영 요청을 받아 Gemini 로 이미지를 분석하는 노드.

    1차 = 원거리. 멀리서도 믿을 수 있는 것만 물어본다.
    2차 = 접근 후. 가까이 왔으니 재질·상태까지 물어본다.

    언제 찍을지는 observe_coordinator 가 정한다. 이 노드는 요청이 오면 분석만 한다.
    """

    def __init__(self):
        super().__init__('gemini_vision_node')

        # 제미나이 API 키 셋업 (구글 AI 스튜디오에서 발급받은 키 입력)
        self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

        # ##################### sub #####################
        # YOLO 노드가 1차 / 2차 crop 을 각각 다른 토픽으로 발행한다
        self.create_subscription(
            CompressedImage, '/vla/trigger_image_1st/compressed',
            self.image_cb_1st, 10)
        self.create_subscription(
            CompressedImage, '/vla/trigger_image_2nd/compressed',
            self.image_cb_2nd, 10)

        # ##################### pub #####################
        # 1차와 2차를 같은 토픽으로 내보내면 호기심 판단 노드가
        # 2차 데이터에도 판단을 돌려버린다. 그래서 나눠 놓는다.
        self.scene_pub_1st = self.create_publisher(
            SemanticLabel, '/perception/scene_data_1st', 10)
        self.scene_pub_2nd = self.create_publisher(
            SemanticLabel, '/perception/scene_data_2nd', 10)

        self.bridge = CvBridge()

        # 데이터셋 저장하기 위한 경로 지정
        self.declare_parameter(
            "dataset_dir",
            "/home/kim/ProjectOdi/Odi_ws/src/perception/dataset")
        self.dataset_dir = self.get_parameter("dataset_dir").value

        self.image_dir = os.path.join(self.dataset_dir, "images")
        self.scene_dir = os.path.join(self.dataset_dir, "scenes")
        os.makedirs(self.image_dir, exist_ok=True)
        os.makedirs(self.scene_dir, exist_ok=True)

        # ---------------- 1차 프롬프트 (원거리) ----------------
        # 멀리서 재질이나 상태를 물어보면 Gemini 는 모른다고 하지 않고 지어낸다.
        # 그래서 원거리에서도 믿을 수 있는 3개만 물어본다.
        self.first_prompt = """
                                당신은 탐사 로봇의 시각 인지 모듈입니다.
                                이 이미지는 물체와 어느 정도 떨어진 거리에서 촬영되었습니다.

                                입력된 이미지를 분석하여 아래 JSON 형식으로만 응답하세요.

                                {
                                    "object_name": "",
                                    "primary_color": "",
                                    "shape": ""
                                }

                                규칙

                                - object_name
                                물체의 대표 이름을 영어 소문자로 작성합니다.
                                예시: bottle, chair, box, person, laptop, backpack

                                - primary_color
                                가장 눈에 띄는 색상을 영어 소문자로 작성합니다.
                                예시: red, blue, black, white

                                - shape
                                대표적인 형태를 영어 소문자로 작성합니다.
                                가능한 값: rectangle, cylinder, sphere, cube, irregular

                                거리가 멀어 확실하지 않은 항목은 추측하지 말고 "unknown" 을 작성하세요.
                                반드시 JSON만 출력하세요.
                                Markdown이나 설명은 절대 출력하지 마세요.
                            """

        # ---------------- 2차 프롬프트 (근접) ----------------
        self.second_prompt = """
                                당신은 탐사 로봇의 시각 인지 모듈입니다.
                                이 이미지는 물체 바로 앞에서 근접 촬영되었습니다.

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
                                두 번째로 많이 보이는 색상입니다. 없다면 "none" 을 작성합니다.

                                - material
                                추정되는 재질을 영어 소문자로 작성합니다.
                                가능한 값: plastic, metal, wood, fabric, glass, paper, rubber

                                - shape
                                대표적인 형태를 영어 소문자로 작성합니다.
                                가능한 값: rectangle, cylinder, sphere, cube, irregular

                                - condition
                                물체의 현재 상태를 영어 소문자로 작성합니다.
                                가능한 값: new, normal, old, dirty, damaged

                                확실하지 않은 항목은 추측하지 말고 "unknown" 을 작성하세요.
                                반드시 JSON만 출력하세요.
                                Markdown이나 설명은 절대 출력하지 마세요.
                            """

        # 제미니 모델
        self.model = 'gemini-3.5-flash-lite'
        self.get_logger().info('vla 입니다 ^^ (1차/2차 분리 버전)')

    # ---------------- 입력 ----------------

    def image_cb_1st(self, msg):
        self.handle_image(msg, '1st')

    def image_cb_2nd(self, msg):
        self.handle_image(msg, '2nd')

    # ---------------- 본체 ----------------

    def handle_image(self, msg, stage):
        self.get_logger().info(
            '[%s] 촬영 요청 수신. Gemini 분석 시작...' % stage)

        if stage == '1st':
            prompt = self.first_prompt
        else:
            prompt = self.second_prompt

        # 1. ROS CompressedImage 메시지를 OpenCV 이미지로 변환
        frame = self.bridge.compressed_imgmsg_to_cv2(msg, "bgr8")

        # 2. OpenCV 이미지를 JPEG 바이트(Bytes) 배열로 인코딩
        success, encoded_image = cv2.imencode('.jpg', frame)
        if not success:
            self.get_logger().error('이미지 인코딩에 실패했습니다.')
            return

        image_bytes = encoded_image.tobytes()

        # 3. Gemini 호출. 여기서 터지면 API 문제다.
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type='image/jpeg',
                    ),
                    prompt
                ]
            )
        except Exception as e:
            self.get_logger().error('Gemini API 호출 실패: %s' % str(e))
            return

        if response is None or response.text is None:
            self.get_logger().error('Gemini 응답이 비어 있음')
            return

        print("\n" + "=" * 40)
        print("[Gemini %s 분석 결과]: %s" % (stage, response.text.strip()))
        print("=" * 40 + "\n")

        # 4. JSON 파싱. 여기서 터지면 API 가 아니라 응답 형식 문제다.
        try:
            scene_data = self.parse_json(response.text)
        except Exception as e:
            self.get_logger().error(
                'JSON 파싱 실패 (API 는 정상): %s / 원문: %s'
                % (str(e), response.text.strip()[:200]))
            return

        self.save_dataset(frame, scene_data, stage)

    def parse_json(self, text):
        """
        프롬프트로 막아도 Gemini 가 ```json 으로 감싸서 주는 경우가 있다.
        펜스가 있으면 벗겨내고 파싱한다.
        """
        t = text.strip()
        if t.startswith('```'):
            t = t.split('```')[1]
            if t.startswith('json'):
                t = t[4:]
        return json.loads(t.strip())

    # ---------------- 저장 / 발행 ----------------

    def save_dataset(self, frame, scene_data, stage):
        # 파일 이름 생성. 어느 단계인지 이름에 남겨야 나중에 구분된다.
        file_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

        image_name = "%s_%s.jpg" % (file_id, stage)
        json_name = "%s_%s.json" % (file_id, stage)

        image_path = os.path.join(self.image_dir, image_name)
        scene_path = os.path.join(self.scene_dir, json_name)

        cv2.imwrite(image_path, frame)

        # SemanticLabel 채우기.
        # 1차에는 secondary_color / material / condition 이 없다.
        # 없는 건 빈 문자열로 남겨서 "아직 모른다" 는 뜻이 되게 한다.
        out = SemanticLabel()
        out.object_name = scene_data.get("object_name", "")
        out.object_primary_color = scene_data.get("primary_color", "")
        out.object_secondary_color = scene_data.get("secondary_color", "")
        out.object_material = scene_data.get("material", "")
        out.object_shape = scene_data.get("shape", "")
        out.object_condition = scene_data.get("condition", "")

        # 추가 정보 저장
        scene_data["image"] = image_name
        scene_data["timestamp"] = file_id
        scene_data["stage"] = stage

        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(scene_data, f, ensure_ascii=False, indent=4)

        self.get_logger().info("Dataset Saved : %s" % image_name)

        self.publish(out, stage)

    def publish(self, msg, stage):
        if stage == '1st':
            self.scene_pub_1st.publish(msg)
        else:
            self.scene_pub_2nd.publish(msg)
        self.get_logger().info("[%s] 성공적으로 보냈다 ^^" % stage)


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