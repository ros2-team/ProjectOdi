"""
2단계: ROS 연결.

state 에 쓰기만 한다. app 을 import 하지 않는다.
그래서 이 파일이 터져도 웹 서버는 살아있고, 화면은 마지막 상태를 유지한다.

지금 붙어 있는 것 (실제로 퍼블리시되는 토픽):
    /camera/image_raw/compressed  → 카메라
    /odom                         → 위치 (지도용으로 쌓아둔다)
    /battery_state                → 배터리

아직 없는 것 (팀에 요청 필요):
    /odi/mission_state   미션 상태 + 현재 행동
    /odi/discovery       발견 이벤트

    CuriosityDecision 은 지금 서비스 응답으로만 나가서 브리지가 받을 수 없다.
    /curiosity/evaluate 를 호출하는 미션 노드가 결과를 토픽으로 한 번 더
    쏴줘야 한다.
"""

import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, CompressedImage

import config
from bridge import frames, state

MEDIA_DIR = config.STATIC_DIR / "media"


class OdiBridgeNode(Node):

    def __init__(self):
        super().__init__("odi_web_bridge")

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)

        self._disk_last = 0.0
        self._path = []          # [(x, y), …] 지도 붙일 때 픽셀로 변환한다

        # 센서 토픽은 sensor_data QoS(best effort)로 받아야 한다.
        # 기본 QoS(reliable)로 구독하면 퍼블리셔와 안 맞아서 콜백이 아예 안 온다.
        self.create_subscription(
            CompressedImage, config.TOPIC_CAMERA,
            self.on_camera, qos_profile_sensor_data)

        self.create_subscription(Odometry, config.TOPIC_ODOM, self.on_odom, 10)
        self.create_subscription(
            BatteryState, config.TOPIC_BATTERY,
            self.on_battery, qos_profile_sensor_data)

        # ── 여기부터는 토픽이 생기면 주석을 푼다 ────────────────
        #
        # from odi_interfaces.msg import MissionState, DiscoveryEvent
        #
        # self.create_subscription(
        #     MissionState, config.TOPIC_MISSION, self.on_mission, 10)
        # self.create_subscription(
        #     DiscoveryEvent, config.TOPIC_DISCOVERY, self.on_discovery, 10)

        # 미션 노드가 시간을 내려주기 전까지는 브리지가 자체적으로 센다
        self.create_timer(1.0, self.on_tick)

        self.get_logger().info("웹 브리지 노드 시작")

    # ============================================================
    # 지금 붙어 있는 것
    # ============================================================

    def on_camera(self, msg):
        """프레임은 메모리로, 파일은 느리게.

        스트림은 frames 버퍼에서 바로 나가고,
        latest.jpg 는 일기용이라 초당 16장이 필요 없다.
        이미지 자체는 웹소켓에 태우지 않는다 — 수백 KB 를 1Hz 로 밀면 막힌다.
        """
        jpeg = bytes(msg.data)

        # ① 스트림용 — 매 프레임. 메모리라 싸다
        frames.publish(jpeg)

        # ② 디스크 — 1초에 한 번이면 충분
        now = time.time()
        if now - self._disk_last < config.DISK_SAVE_SEC:
            return
        self._disk_last = now

        try:
            (MEDIA_DIR / "latest.jpg").write_bytes(jpeg)
        except Exception as e:
            self.get_logger().error(f"카메라 저장 실패: {e}")
            return

        # url 은 안 보낸다. 프론트가 /camera/stream 을 직접 물고 있다.
        state.patch(camera={"live": True, "at": time.strftime("%H:%M:%S")})

    def on_odom(self, msg):
        """5단계에서 지도 위 경로로 쓴다. 지금은 쌓아만 둔다."""
        p = msg.pose.pose.position
        if not self._path or (abs(p.x - self._path[-1][0]) > 0.05 or
                              abs(p.y - self._path[-1][1]) > 0.05):
            self._path.append((p.x, p.y))
            if len(self._path) > 2000:
                self._path = self._path[::2]      # 너무 길어지면 솎아낸다

    def on_battery(self, msg):
        pass    # 화면에 배터리 숫자는 안 띄운다. 캐릭터가 죽는다.

    def on_tick(self):
        with state.LOCK:
            state.STATE["elapsed_sec"] += 1

    # ============================================================
    # 토픽이 생기면 쓸 것
    # ============================================================

    def on_mission(self, msg):
        state.patch(
            mission=msg.mission_state,
            behavior=msg.behavior,
            explore_mode=msg.explore_mode,
            motivation=float(msg.motivation),
            observed_count=int(msg.observed_count),
        )

    def on_discovery(self, msg):
        """발견 하나가 두 번에 걸쳐 온다.

        1) 처음 만났을 때  — decision 없이 label 만
        2) 판단이 끝났을 때 — decision 채워서

        detection_id 로 짝을 맞춘다.
        """
        item = {
            "detection_id": msg.detection_id,
            "at": time.strftime("%H:%M"),
            "observed": bool(msg.observed),
            "photo_url": msg.photo_url or None,
            "label": {
                "object_name":            msg.label.object_name,
                "object_primary_color":   msg.label.object_primary_color,
                "object_secondary_color": msg.label.object_secondary_color,
                "object_material":        msg.label.object_material,
                "object_shape":           msg.label.object_shape,
                "object_condition":       msg.label.object_condition,
            },
            "decision": None,
        }

        if msg.has_decision:
            d = msg.decision
            item["decision"] = {
                "action":                d.action,
                "curiosity_score":       float(d.curiosity_score),
                "similarity_score":      float(d.similarity_score),
                "novel_features":        list(d.novel_features),
                "duplicated_features":   list(d.duplicated_features),
                "visit_count":           int(d.visit_count),
                "compared_record_count": int(d.compared_record_count),
            }

        # 이미 있으면 갱신, 없으면 추가
        fields = {k: v for k, v in item.items() if k != "detection_id"}
        if not state.update_discovery(msg.detection_id, **fields):
            state.add_discovery(item)


# ============================================================

_node = None


def spin_in_thread():
    """rclpy 를 데몬 스레드에서 돌린다.

    Flask 가 메인 스레드를 잡고 있어야 하므로 spin 을 여기서 하면 안 된다.
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