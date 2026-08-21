"""
ROS2 연결 — 로봇 세계와 웹 세계가 만나는 지점.

ROS2 노드 하나를 만들어 토픽을 구독하고,
받은 내용을 state / frames 에 써 넣는다. 그게 전부다.
app 을 import 하지 않는다 — 이 파일은 웹이 존재하는지도 모른다.
"""

# ┌─ 연결 지도 ────────────────────────────────────────────────
# │ import 하는 것 :
# │     config                토픽 이름, 사진 폴더
# │     bridge.state          로봇 상태 (쓰기만)
# │     bridge.frames         카메라 사진 (쓰기만)
# │
# │ ★ app.py 를 import 하지 않는다.
# │
# │ 부르는 파일 : run.py 의 start_producers()
# │              (config.USE_FAKE = False 일 때만)
# └────────────────────────────────────────────────────────────

# ════════════════════════════════════════════════════════════
# 구독하는 토픽과 화면의 대응
#
#   /camera/image_raw/compressed   CompressedImage       카메라 영상
#   /odom                          Odometry              위치 (지도용)
#
#   MissionState        →  화면 라우팅 (탐험 / 복귀 / 일기 …)
#   BehaviorState       →  상단 큰 문구
#   DetectedObjectArray →  "다음 차례 · bottle, backpack"
#
#   ★ 발견 하나가 세 메시지에 걸쳐 온다. detection_id 로 묶인다.
#   EncounterResult     →  ① "저기 뭔가 있어요"     사진 1장 + 라벨
#   CuriosityDecision   →  ② "처음 보는 물체예요"   판단 결과
#   ObservationResult   →  ③ "관찰 완료"            대표 사진 + 요약
#
#   위 셋은 원래 액션 result / 서비스 응답이라 브리지가 직접 못 받는다.
#   미션 노드가 토픽으로 재발행해 줘야 한다. (docs/토픽요청.md 참조)
# ════════════════════════════════════════════════════════════

import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, CompressedImage

from odi_interfaces.msg import (
    BehaviorState,
    CuriosityDecision,
    DetectedObjectArray,
    EncounterResult,
    MissionState,
    ObservationResult,
)

import config
from bridge import frames, state

MEDIA_DIR = config.STATIC_DIR / "media"


def to_web_path(fs_path):
    """로봇이 저장한 파일 경로를 브라우저가 열 수 있는 주소로 바꾼다.

        /home/yyj/odi_photos/obs_12.jpg   →   /media/obs/obs_12.jpg

    브라우저는 로봇의 파일시스템을 직접 못 읽는다.
    웹서버가 중계해야 하므로 /media/... 형태로 바꿔줘야 한다.
    """
    if not fs_path:
        return None
    if fs_path.startswith("/media/"):     # 이미 웹 경로면 그대로
        return fs_path
    name = fs_path.rsplit("/", 1)[-1]     # 파일명만 뽑는다
    return f"/media/obs/{name}"


def label_to_dict(lab):
    """SemanticLabel → 딕셔너리.

    키 이름을 절대 바꾸지 않는다.
    novel_features 에 'object_material' 같은 필드명이 그대로 들어오는데,
    프론트가 그 이름으로 '재질' 이라는 한국어를 찾기 때문이다.
    (static/js/schema.js 의 FEAT 표)
    """
    return {
        "object_name":            lab.object_name,
        "object_primary_color":   lab.object_primary_color,
        "object_secondary_color": lab.object_secondary_color,
        "object_material":        lab.object_material,
        "object_shape":           lab.object_shape,
        "object_condition":       lab.object_condition,
    }


class OdiBridgeNode(Node):

    def __init__(self):
        super().__init__("odi_web_bridge")

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / "obs").mkdir(exist_ok=True)

        self._disk_last = 0.0
        self._path = []
        self._exploring_since = None    # EXPLORING 진입 시각 → 경과 시간 계산

        # ── 센서 ────────────────────────────────────────────
        # ★ QoS 가 맞아야 붙는다.
        #   센서는 BEST_EFFORT 로 발행되는데 구독자가 기본값(RELIABLE)을
        #   쓰면 에러도 없이 콜백이 영원히 안 불린다.
        self.create_subscription(
            CompressedImage, config.TOPIC_CAMERA,
            self.on_camera, qos_profile_sensor_data)
        self.create_subscription(
            Odometry, config.TOPIC_ODOM, self.on_odom, 10)
        self.create_subscription(
            BatteryState, config.TOPIC_BATTERY,
            self.on_battery, qos_profile_sensor_data)

        # ── 미션 ────────────────────────────────────────────
        self.create_subscription(
            MissionState, config.TOPIC_MISSION, self.on_mission, 10)
        self.create_subscription(
            BehaviorState, config.TOPIC_BEHAVIOR, self.on_behavior, 10)
        self.create_subscription(
            DetectedObjectArray, config.TOPIC_DETECTIONS, self.on_detections, 10)

        # ── 발견 3 단계 ──────────────────────────────────────
        self.create_subscription(
            EncounterResult, config.TOPIC_ENCOUNTER, self.on_encounter, 10)
        self.create_subscription(
            CuriosityDecision, config.TOPIC_DECISION, self.on_decision, 10)
        self.create_subscription(
            ObservationResult, config.TOPIC_OBSERVATION, self.on_observation, 10)

        self.create_timer(1.0, self.on_tick)
        self.get_logger().info("웹 브리지 노드 시작")

    # ════════════════════════════════════════════════════════
    # 센서
    # ════════════════════════════════════════════════════════

    def on_camera(self, msg):
        """프레임은 메모리로, 파일은 느리게.

        스트림은 frames 버퍼에서 바로 나가고, latest.jpg 는 미리보기용이다.
        관찰 사진은 로봇 쪽에서 저장하므로 브리지는 만들지 않는다.
        """
        jpeg = bytes(msg.data)
        frames.publish(jpeg)                       # 매 프레임

        now = time.time()
        if now - self._disk_last < config.DISK_SAVE_SEC:
            return
        self._disk_last = now
        try:
            (MEDIA_DIR / "latest.jpg").write_bytes(jpeg)
        except Exception as e:
            self.get_logger().error(f"카메라 저장 실패: {e}")
            return
        # 프론트는 이 값이 null 에서 벗어나야 <img> 를 만든다
        state.patch(camera={"live": True, "at": time.strftime("%H:%M:%S")})

    def on_odom(self, msg):
        """5 단계에서 지도 위 경로선으로 쓴다. 지금은 쌓아만 둔다."""
        p = msg.pose.pose.position
        if not self._path or (abs(p.x - self._path[-1][0]) > 0.05 or
                              abs(p.y - self._path[-1][1]) > 0.05):
            self._path.append((p.x, p.y))
            if len(self._path) > 2000:
                self._path = self._path[::2]

    def on_battery(self, msg):
        """받기만 하고 화면에 안 띄운다.
        배터리 퍼센트를 띄우면 화면이 관제 대시보드가 되어 캐릭터가 죽는다."""
        pass

    # ════════════════════════════════════════════════════════
    # 미션 · 행동
    # ════════════════════════════════════════════════════════

    def on_mission(self, msg):
        """MissionState → 화면 라우팅.

        msg.state 값이 그대로 화면을 결정한다.
            EXPLORING  → 탐험 화면
            RETURNING  → "집으로 돌아가는 중"
            REFLECTING → "일기 쓰는 중"
            COMPLETED  → 일기 화면으로 전환

        msg.detail 에 JSON 이 들어오면 의욕과 session_id 를 꺼낸다.
        (메시지 수정 없이 값을 실어보내는 방법 — docs/토픽요청.md 5절)
        """
        prev = state.snapshot()["mission"]
        state.patch(mission=msg.state)

        if msg.detail:
            try:
                import json
                extra = json.loads(msg.detail)
                state.patch(
                    motivation=extra.get("motivation"),
                    session_id=extra.get("session_id"),
                )
            except Exception:
                pass    # detail 이 JSON 이 아니면 그냥 무시한다

        # EXPLORING 에 처음 진입하면 시계를 켠다
        if msg.state == "EXPLORING" and prev != "EXPLORING":
            if self._exploring_since is None:
                self._exploring_since = time.time()
        elif msg.state in ("IDLE", "PREPARING"):
            self._exploring_since = None

    def on_behavior(self, msg):
        """BehaviorState → 상단 큰 문구.

        msg.behavior 를 schema.js 의 SAY 표가 사람 말로 번역한다.
            FIRST_ENCOUNTER → "처음 보는 물체 앞에 섰어요"

        msg.detail / msg.status 는 지금 쓰지 않는다.
        """
        state.patch(behavior=msg.behavior)

    def on_detections(self, msg):
        """DetectedObjectArray → "다음 차례 · bottle, backpack"

        한 장면에서 여러 물체가 잡히면 순서대로 처리하는데,
        그 대기열을 화면에 보여준다.
        맨 앞은 지금 처리 중인 것이므로 빼고, 나머지만 큐로 표시한다.
        """
        names = [o.class_name for o in msg.objects]
        state.patch(queue=names[1:] if len(names) > 1 else [])

    def on_tick(self):
        """경과 시간. MissionState 에 시간 필드가 없어서 브리지가 센다."""
        if self._exploring_since is None:
            return
        with state.LOCK:
            state.STATE["elapsed_sec"] = int(time.time() - self._exploring_since)

    # ════════════════════════════════════════════════════════
    # 발견 3 단계 — 전부 detection_id 로 묶인다
    # ════════════════════════════════════════════════════════

    def on_encounter(self, msg):
        """① EncounterResult — 물체를 처음 만났다.

        아직 호기심 판단 전이라 decision 은 None.
        화면에는 "저기 뭔가 있어요. 가까이 가볼게요."가 뜬다.
        """
        if not msg.success:
            self.get_logger().warn(f"encounter 실패: {msg.failure_reason}")
            return

        item = {
            "detection_id": msg.detection_id,
            "at": time.strftime("%H:%M"),
            "observed": False,
            "photo_url": to_web_path(msg.image_path),
            "label": label_to_dict(msg.label),
            "decision": None,
        }
        fields = {k: v for k, v in item.items() if k != "detection_id"}
        if not state.update_discovery(msg.detection_id, **fields):
            state.add_discovery(item)

    def on_decision(self, msg):
        """② CuriosityDecision — 호기심 판단이 끝났다.

        이 필드들로 화면 문장이 생성된다 (static/js/schema.js 의 describe).
            visit_count = 0                     → "처음 보는 물체예요"
            visit_count = 3, novel = []         → "3번째 보는 거예요"
            novel = [object_condition]          → "전에도 봤는데 상태가 달라요"
            compared_record_count = 0           → "이런 건 굳이 안 봐도 돼요"

        ★ visit_count 가 .msg 에 없으면 getattr 이 0 을 돌려주고
          화면에 "0번째 보는 거예요"가 뜬다. 필드 추가가 필요하다.
        """
        decision = {
            "action":                msg.action,
            "curiosity_score":       float(msg.curiosity_score),
            "similarity_score":      float(msg.similarity_score),
            "novel_features":        list(msg.novel_features),
            "duplicated_features":   list(msg.duplicated_features),
            "visit_count":           int(getattr(msg, "visit_count", 0)),
            "compared_record_count": int(msg.compared_record_count),
        }

        # EncounterResult 가 먼저 왔으면 갱신, 순서가 뒤집혔으면 새로 만든다.
        # (ROS 는 토픽 간 도착 순서를 보장하지 않는다)
        if not state.update_discovery(msg.detection_id, decision=decision):
            state.add_discovery({
                "detection_id": msg.detection_id,
                "at": time.strftime("%H:%M"),
                "observed": False,
                "photo_url": None,
                "label": {"object_name": "?"},
                "decision": decision,
            })

    def on_observation(self, msg):
        """③ ObservationResult — 관찰이 끝났다.

        화면에서 "관찰 완료" 태그가 붙고 사진이 빠진다.
        (사진은 지금 보고 있는 물체에만 표시한다)

        msg.diary_summary 는 일기용 한 줄 요약이다.
        지금 탐험 화면에서는 안 쓰지만, DB 에 저장되면
        일기 화면에서 entries[].text 의 재료가 될 수 있다.
        """
        if not msg.success:
            self.get_logger().warn(f"observation 실패: {msg.failure_reason}")
            return

        state.update_discovery(
            msg.detection_id,
            observed=True,
            photo_url=to_web_path(msg.representative_image_path),
            label=label_to_dict(msg.detailed_label),   # 관찰 후 더 자세해진 라벨
        )

        # 관찰 개수는 브리지가 직접 센다. 로봇이 따로 보낼 필요가 없다.
        snap = state.snapshot()
        done = sum(1 for d in snap["discoveries"] if d.get("observed"))
        state.patch(observed_count=done)


# ════════════════════════════════════════════════════════════

_node = None


def spin_in_thread():
    """rclpy 를 별도 스레드에서 돌린다.

    rclpy.spin() 도 Flask 의 app.run() 도 무한 루프라
    한 스레드에서 둘 다 못 돌린다.
    ROS 를 스레드로 보내고 메인 스레드는 Flask 에게 준다.

    daemon=True : 메인이 끝나면 같이 죽는다.
    없으면 Ctrl+C 를 눌러도 안 죽어서 8000 포트를 계속 잡고 있는다.
    """
    global _node
    rclpy.init()
    _node = OdiBridgeNode()

    def _spin():
        try:
            rclpy.spin(_node)
        except Exception as e:
            print(f"[ros] spin 종료: {e}")

    threading.Thread(target=_spin, daemon=True).start()
    print("[ros] odi_web_bridge 노드 실행 중")