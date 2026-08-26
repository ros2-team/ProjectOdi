#!/usr/bin/env python3
"""
가짜 로봇 — 실제 ROS 토픽으로 시나리오를 쏘는 테스트 도구.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이게 왜 필요한가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bridge/fake.py 는 ROS 를 거치지 않고 state 에 직접 쓴다.
화면 확인에는 좋지만 "토픽 → 브리지 → 화면" 경로는 검증되지 않는다.

이 파일은 진짜 ROS 토픽으로 쏘기 때문에 그 경로를 전부 통과한다.
로봇 팀이 발행을 시작하기 전에 웹이 제대로 받는지 확인할 수 있고,
발행해야 할 내용의 예시이기도 하다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
실행
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 터미널 1 — 브리지 (config.USE_FAKE = False 여야 한다)
    source ~/ProjectOdi/Odi_ws/install/setup.bash
    cd ~/ProjectOdi/web_ws
    python3 run.py

    # 터미널 2 — 이 파일
    source ~/ProjectOdi/Odi_ws/install/setup.bash
    cd ~/ProjectOdi/web_ws
    python3 tools/fake_robot.py

브라우저에서 http://localhost:8000

Ctrl+C 로 멈추고, 다시 실행하면 처음부터 돈다.
"""

import shutil
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node

from odi_interfaces.msg import (
    BehaviorState,
    CuriosityDecision,
    EncounterResult,
    MissionState,
    ObservationResult,
    SemanticLabel,
)

# web_ws 를 import 경로에 넣어 config 의 토픽 이름을 그대로 쓴다.
# 토픽 이름을 여기 또 적어두면 나중에 브리지와 어긋난다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


PHOTO_DIR = config.STATIC_DIR / "media" / "obs"
LATEST = config.STATIC_DIR / "media" / "latest.jpg"


def lab(name, primary, secondary, material, shape, condition):
    m = SemanticLabel()
    m.object_name = name
    m.object_primary_color = primary
    m.object_secondary_color = secondary
    m.object_material = material
    m.object_shape = shape
    m.object_condition = condition
    m.object_special_features = []
    m.raw_json = ""
    return m


# ════════════════════════════════════════════════════════════
# 시나리오
#
# (초, 동작) 순서로 실행된다.
# 동작은 아래 FakeRobot 의 메서드 이름과 인자다.
# ════════════════════════════════════════════════════════════

SCENARIO = [
    (0,   "behavior", "EXPLORE"),

    # ── ① chair : 3번째 보는 물건이라 지나친다 ────────────
    (6,   "behavior", "FIRST_ENCOUNTER"),
    (6,   "encounter", "d1", lab("chair", "검정", "회색", "플라스틱", "각진", "깨끗함")),
    (10,  "behavior", "EVALUATE_CURIOSITY"),
    (14,  "decision", "d1", "IGNORE", 0.18, 0.91, [], ["object_material"], 3, 12),
    (16,  "behavior", "EXPLORE"),

    # ── ② bottle : 처음 보는 물건 → 관찰 1 ────────────────
    (22,  "behavior", "FIRST_ENCOUNTER"),
    (22,  "encounter", "d2", lab("bottle", "투명", "파랑", "유리", "원통", "깨끗함")),
    (26,  "behavior", "EVALUATE_CURIOSITY"),
    (30,  "decision", "d2", "OBSERVE", 0.81, 0.42,
          ["object_material", "object_primary_color"], [], 0, 12),
    (32,  "behavior", "OBSERVE"),
    (44,  "observation", "d2", lab("bottle", "투명", "파랑", "유리", "원통", "깨끗함"),
          "표면이 매끈하고 빛이 통과했다."),
    (44,  "motivation", 0.75),
    (46,  "behavior", "EXPLORE"),

    # ── ③ person : IGNORE_CLASSES 로 걸러진다 ─────────────
    (52,  "behavior", "FIRST_ENCOUNTER"),
    (52,  "encounter", "d3", lab("person", "", "", "", "", "")),
    (56,  "decision", "d3", "IGNORE", 0.0, 0.0, [], [], 0, 0),
    (58,  "behavior", "EXPLORE"),

    # ── ④ plant : 전에 봤는데 상태가 달라졌다 → 관찰 2 ────
    (64,  "behavior", "FIRST_ENCOUNTER"),
    (64,  "encounter", "d4", lab("plant", "초록", "갈색", "흙", "갈라진", "시듦")),
    (68,  "behavior", "EVALUATE_CURIOSITY"),
    (72,  "decision", "d4", "OBSERVE", 0.67, 0.88,
          ["object_condition"], ["object_name"], 2, 14),
    (74,  "behavior", "OBSERVE"),
    (86,  "observation", "d4", lab("plant", "초록", "갈색", "흙", "갈라진", "시듦"),
          "잎이 축 늘어져 있었다."),
    (86,  "motivation", 0.50),
    (88,  "behavior", "EXPLORE"),

    # ── ⑤ cup : 처음 보는 물건 → 관찰 3 ───────────────────
    (94,  "behavior", "FIRST_ENCOUNTER"),
    (94,  "encounter", "d5", lab("cup", "흰색", "파랑", "도자기", "원통", "깨끗함")),
    (98,  "behavior", "EVALUATE_CURIOSITY"),
    (102, "decision", "d5", "OBSERVE", 0.88, 0.31, [], [], 0, 15),
    (104, "behavior", "OBSERVE"),
    (116, "observation", "d5", lab("cup", "흰색", "파랑", "도자기", "원통", "깨끗함"),
          "손잡이가 달려 있고 파란 무늬가 있었다."),
    (116, "motivation", 0.25),
    (118, "behavior", "EXPLORE"),

    # ── ⑥ backpack : 전에 봤는데 재질이 다르다 → 관찰 4 ───
    (124, "behavior", "FIRST_ENCOUNTER"),
    (124, "encounter", "d6", lab("backpack", "회색", "검정", "천", "둥근", "낡음")),
    (128, "behavior", "EVALUATE_CURIOSITY"),
    (132, "decision", "d6", "OBSERVE", 0.72, 0.85,
          ["object_material"], ["object_name", "object_shape"], 1, 16),
    (134, "behavior", "OBSERVE"),
    (146, "observation", "d6", lab("backpack", "회색", "검정", "천", "둥근", "낡음"),
          "겉이 거칠었고 열려 있진 않았다."),
    (146, "motivation", 0.0),

    # ── 복귀 → 일기 ──────────────────────────────────────
    (150, "mission", "RETURNING"),
    (158, "mission", "REFLECTING"),
    (168, "mission", "COMPLETED"),
]


class FakeRobot(Node):

    def __init__(self):
        super().__init__("fake_robot")

        self.pub_mission = self.create_publisher(
            MissionState, config.TOPIC_MISSION, 10)
        self.pub_behavior = self.create_publisher(
            BehaviorState, config.TOPIC_BEHAVIOR, 10)
        self.pub_encounter = self.create_publisher(
            EncounterResult, config.TOPIC_ENCOUNTER, 10)
        self.pub_decision = self.create_publisher(
            CuriosityDecision, config.TOPIC_DECISION, 10)
        self.pub_observation = self.create_publisher(
            ObservationResult, config.TOPIC_OBSERVATION, 10)

        PHOTO_DIR.mkdir(parents=True, exist_ok=True)

        self.mission = "EXPLORING"
        self.motivation = 1.0
        self.session_id = "3"
        self.t = 0
        self.step = 0

        # MissionState 는 1Hz 로 계속 보낸다.
        # 웹이 마지막 수신 시각으로 연결 상태를 판단하기 때문에,
        # 상태가 안 바뀌어도 계속 쏴야 "연결 끊김" 배너가 안 뜬다.
        self.create_timer(1.0, self.tick)

        self.get_logger().info("가짜 로봇 시작 — 브라우저에서 localhost:8000")

    # ────────────────────────────────────────────────────────

    def tick(self):
        # 시나리오에서 지금 시각까지의 동작을 전부 실행
        while self.step < len(SCENARIO) and SCENARIO[self.step][0] <= self.t:
            entry = SCENARIO[self.step]
            self.step += 1
            self.run_action(entry[1], entry[2:])

        self.send_mission()
        self.t += 1

        if self.step == len(SCENARIO) and self.t > SCENARIO[-1][0] + 5:
            self.get_logger().info("시나리오 끝. Ctrl+C 로 종료하세요.")
            self.step += 1      # 다음 tick 부터는 이 조건을 안 탄다

    def run_action(self, kind, args):
        try:
            getattr(self, "do_" + kind)(*args)
        except Exception as e:
            # 한 동작이 실패해도 나머지는 계속 돌게 한다.
            # 메시지 필드명이 다르면 여기서 잡힌다.
            self.get_logger().error(f"[{kind}] 실패: {e}")

    # ── 동작들 ──────────────────────────────────────────────

    def do_mission(self, state):
        self.mission = state
        self.get_logger().info(f"미션 → {state}")

    def do_motivation(self, value):
        self.motivation = value
        self.get_logger().info(f"의욕 → {int(value * 100)}%")

    def send_mission(self):
        """1Hz. detail 에 JSON 으로 의욕과 session_id 를 싣는다.

        MissionState 에 motivation 필드가 없어서 쓰는 방법이다.
        메시지를 수정하지 않아도 되고, 웹은 이 형식을 이미 받도록 되어 있다.
        """
        import json
        m = MissionState()
        m.state = self.mission
        m.detail = json.dumps({
            "motivation": self.motivation,
            "session_id": self.session_id,
        })
        m.updated_at = self.get_clock().now().to_msg()
        self.pub_mission.publish(m)

    def do_behavior(self, behavior):
        b = BehaviorState()
        b.behavior = behavior
        b.status = "RUNNING"
        b.detail = ""
        b.updated_at = self.get_clock().now().to_msg()
        self.pub_behavior.publish(b)
        self.get_logger().info(f"행동 → {behavior}")

    def do_encounter(self, detection_id, label):
        """① 물체를 처음 만났다.

        사진은 카메라가 방금 저장한 latest.jpg 를 복사해서 쓴다.
        실제 로봇은 관찰 시점에 찍은 사진 경로를 넣으면 된다.
        """
        e = EncounterResult()
        e.detection_id = detection_id
        e.success = True
        e.image_path = self.snapshot(f"enc_{detection_id}.jpg")
        e.label = label
        e.started_at = self.get_clock().now().to_msg()
        e.completed_at = self.get_clock().now().to_msg()
        e.failure_reason = ""
        self.pub_encounter.publish(e)
        self.get_logger().info(f"발견 → {label.object_name} ({detection_id})")

    def do_decision(self, detection_id, action, score, similarity,
                    novel, duplicated, visits, compared):
        """② 호기심 판단이 끝났다.

        이 필드들로 화면 문장이 생성된다.
            visit_count = 0                    → "처음 보는 물체예요"
            visit_count = 3, novel = []        → "3번째 보는 거예요"
            novel = [object_condition]         → "전에도 봤는데 상태가 달라요"
            compared_record_count = 0          → "이런 건 굳이 안 봐도 돼요"
        """
        d = CuriosityDecision()
        d.detection_id = detection_id
        d.curiosity_score = float(score)
        d.similarity_score = float(similarity)
        d.action = action
        d.reason = f"Visits={visits}"
        d.novel_features = novel
        d.duplicated_features = duplicated
        d.compared_record_count = compared
        try:
            d.visit_count = visits
        except AttributeError:
            # .msg 에 visit_count 가 없으면 화면에 "0번째"가 뜬다
            self.get_logger().warn("CuriosityDecision 에 visit_count 필드가 없습니다")
        d.evaluated_at = self.get_clock().now().to_msg()
        self.pub_decision.publish(d)
        self.get_logger().info(f"판단 → {detection_id} {action} (visits={visits})")

    def do_observation(self, detection_id, label, summary):
        """③ 관찰이 끝났다. 화면에서 "관찰 완료"로 바뀐다."""
        o = ObservationResult()
        o.detection_id = detection_id
        o.success = True
        path = self.snapshot(f"obs_{detection_id}.jpg")
        o.image_paths = [path] if path else []
        o.representative_image_path = path
        o.detailed_label = label
        o.diary_summary = summary
        o.saved_to_database = True
        o.memory_id = "0"
        o.started_at = self.get_clock().now().to_msg()
        o.completed_at = self.get_clock().now().to_msg()
        o.failure_reason = ""
        self.pub_observation.publish(o)
        self.get_logger().info(f"관찰 완료 → {detection_id}")

    # ────────────────────────────────────────────────────────

    def snapshot(self, filename):
        """카메라가 저장해둔 latest.jpg 를 복사해 관찰 사진처럼 쓴다.

        카메라가 안 돌고 있으면 빈 문자열을 준다.
        그러면 화면에 사진 자리만 비어 보인다.
        """
        if not LATEST.exists():
            return ""
        dst = PHOTO_DIR / filename
        try:
            shutil.copyfile(LATEST, dst)
        except Exception as e:
            self.get_logger().warn(f"사진 복사 실패: {e}")
            return ""
        return str(dst)


def main():
    rclpy.init()
    node = FakeRobot()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()