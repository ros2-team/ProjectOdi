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
# │     bridge.commands       웹이 넣어둔 명령 (읽기만)
# │
# │ ★ app.py 를 import 하지 않는다.
# │   웹에서 오는 명령도 commands 큐를 통해서만 받는다.
# │
# │ 부르는 파일 : run.py 의 start_producers()
# │              (config.USE_FAKE = False 일 때만)
# └────────────────────────────────────────────────────────────

# ════════════════════════════════════════════════════════════
# 구독하는 토픽과 화면의 대응
#
#   /camera/image_raw/compressed   CompressedImage       카메라 영상
#   /odom                          Odometry              위치 갱신 트리거
#   map → base_footprint TF        지도 위 실제 위치/경로
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
# ════════════════════════════════════════════════════════════

import functools
import json
import math
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import (DurabilityPolicy, QoSProfile, ReliabilityPolicy,
                       qos_profile_sensor_data)
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

from nav_msgs.msg import OccupancyGrid, Odometry
from sensor_msgs.msg import BatteryState, CompressedImage
from std_msgs.msg import String

from odi_interfaces.msg import (
    BehaviorState,
    CuriosityDecision,
    DetectedObjectArray,
    EncounterResult,
    MissionState,
    ObservationResult,
)

import config
from bridge import commands, frames, mapper, state

MEDIA_DIR = config.STATIC_DIR / "media"
MAP_PNG = MEDIA_DIR / "map.png"


def safe(fn):
    """콜백 하나가 터져도 rclpy.spin() 이 안 죽게 감싼다.

    ★ 왜 필요한가
      rclpy 는 콜백에서 빠져나온 예외를 잡아주지 않는다.
      그대로 spin() 밖으로 나가면서 ROS 스레드가 통째로 끝난다.

      실제로 겪은 사고 :
        config 에 상수 하나를 안 넣어서 on_battery 가 AttributeError 를 냈고,
        그 한 줄 때문에 카메라도 지도도 전부 멈췄다.
        화면에는 아무 에러도 안 뜨고 그냥 조용히 멎는다.

    ★ 왜 로그만 남기고 넘어가는가
      한 토픽이 실패해도 나머지는 계속 받아야 한다.
      화면이 통째로 멈추는 것보다, 한 항목만 옛날 값에 머무는 게 낫다.
      tools/fake_robot.py 의 run_action 이 쓰는 것과 같은 원칙이다.
    """
    @functools.wraps(fn)
    def wrapped(self, msg):
        try:
            return fn(self, msg)
        except Exception as e:
            self.get_logger().error(f"{fn.__name__} 실패: {e}")
    return wrapped


def to_web_path(fs_path):
    """로봇이 저장한 파일 경로를 브라우저가 열 수 있는 주소로 바꾼다.

        /home/yyj/odi_photos/obs_12.jpg   →   /media/obs/obs_12.jpg

    브라우저는 로봇의 파일시스템을 직접 못 읽는다.
    웹서버가 중계해야 하므로 /media/... 형태로 바꿔줘야 한다.

    폴더 규칙이 정해지면 config.PHOTO_ROOT 를 맞추면 된다.
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
        self.create_subscription(String, '/normal/status', self.on_normal, 10)

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / "obs").mkdir(exist_ok=True)

        self._disk_last = 0.0
        self._battery_last = 0.0        # 배터리 반영 스로틀
        self._path = []                 # 지나온 map 좌표 [(x, y), …]
        self._pose = None               # 지금 map 위치 (x, y)

        # 발견 위치. {detection_id: (x, y, action)}
        #
        # ★ 리스트가 아니라 딕셔너리인 이유
        #   전에는 리스트에 append 하고, 판단이 오면 마지막 항목([-1])의
        #   action 을 채웠다. 한 장면에서 물체가 하나일 때만 맞는 방식이다.
        #   chair / bottle / backpack 이 동시에 잡히면 세 개가 쌓이는데,
        #   먼저 온 판단이 마지막 마커에 붙어서 엉뚱한 점이 주황색이 된다.
        #   detection_id 로 찾으면 순서가 어떻든 제 짝에 붙는다.
        self._markers = {}
        self._exploring_since = None    # EXPLORING 진입 시각 → 경과 시간 계산
        self._session_id = ''

        # 지도
        self._map_msg = None            # 마지막으로 받은 OccupancyGrid
        self._map_seq = 0               # PNG 를 다시 만들 때마다 +1
        self._map_last = 0.0            # 마지막 변환 시각 (스로틀용)

        # 웹 경로와 지도는 반드시 같은 map 프레임을 사용한다.
        # /odom 의 pose 를 그대로 지도에 찍으면 SLAM 재시작 때 생기는
        # map↔odom 회전/이동 오프셋 때문에 경로가 틀어진다.
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        # ── 센서 ────────────────────────────────────────────
        # ★ QoS 가 맞아야 붙는다.
        #   센서는 BEST_EFFORT 로 발행되는데 구독자가 기본값(RELIABLE)을
        #   쓰면 에러도 없이 콜백이 영원히 안 불린다.
        self.create_subscription(
            CompressedImage, config.TOPIC_CAMERA,
            self.on_camera, qos_profile_sensor_data)
        self.create_subscription(
            Odometry, config.TOPIC_ODOM, self.on_odom, 10)
        # ★ 배터리만 QoS 가 다르다.
        #   turtlebot3_node 는 /battery_state 를 RELIABLE 로 발행한다.
        #   카메라처럼 qos_profile_sensor_data(BEST_EFFORT) 로 구독하면
        #   호환이 안 맞아 연결 자체가 안 맺어진다.
        #   에러도 경고도 없이 콜백이 영영 안 불린다 —
        #   ros2 topic info 의 Subscription count 가 0 인 게 유일한 단서다.
        #
        #   규칙 : 구독자가 발행자보다 요구가 세면 안 붙는다.
        #          BEST_EFFORT 발행 + RELIABLE 구독  →  ✗
        #          RELIABLE    발행 + BEST_EFFORT 구독 →  ✓
        #   10 은 depth 10 의 기본 프로파일이고 RELIABLE 이다.
        self.create_subscription(
            BatteryState, config.TOPIC_BATTERY,
            self.on_battery, 10)

        # ★ QoS 를 기본값(VOLATILE)으로 둔다.
        #   TRANSIENT_LOCAL 로 요구하면 VOLATILE 퍼블리셔와 호환이 안 돼서
        #   연결 자체가 안 된다. 에러도 없이 조용히 아무것도 안 온다.
        #   VOLATILE 구독자는 양쪽 다 붙을 수 있다.
        #   cartographer 는 지도를 주기적으로 다시 쏘므로 놓쳐도 곧 받는다.
        self.create_subscription(
            OccupancyGrid, config.TOPIC_MAP, self.on_map, 10)

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

        # ── 웹 → 로봇 ───────────────────────────────────────
        # 지금까지는 전부 받기만 했다. 이게 유일하게 내보내는 토픽이다.
        # 미션 노드가 이걸 구독해서 "START" 를 받으면 탐험을 시작한다.
        self.pub_command = self.create_publisher(
            String, config.TOPIC_COMMAND, 10)

        self.create_timer(1.0, self.on_tick)
        self.get_logger().info("웹 브리지 노드 시작")

    # ════════════════════════════════════════════════════════
    # 센서
    # ════════════════════════════════════════════════════════

    @safe
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

    @safe
    def on_odom(self, msg):
        """odom 수신을 트리거로 map 프레임의 로봇 위치를 기록한다.

        SLAM 을 새로 시작하면 map↔odom 변환은 매 미션 달라질 수 있다.
        따라서 msg.pose.pose.position(odom 좌표)을 웹 지도에 직접 쓰지 않고
        항상 최신 map → base_footprint TF를 읽어 경로/마커와 동일 프레임으로
        맞춘다. PREPARING 중의 이전 TF가 경로에 섞이지 않도록 탐험/복귀 중에만
        기록한다.
        """
        snapshot = state.snapshot()
        if snapshot["mission"] not in ("EXPLORING", "RETURNING"):
            return

        try:
            transform = self._tf_buffer.lookup_transform(
                "map",
                "base_footprint",
                Time(),
            )
        except Exception:
            return

        p = transform.transform.translation
        self._pose = (p.x, p.y)

        # ★ 5cm 이상 움직였을 때만 기록한다.
        #   /odom 은 초당 수십 번 온다. 전부 저장하면 1 분에 수천 점이 되고,
        #   그걸 선으로 그리면 뭉개진 덩어리가 된다.
        if not self._path or (abs(p.x - self._path[-1][0]) > 0.05 or
                              abs(p.y - self._path[-1][1]) > 0.05):
            self._path.append((p.x, p.y))
            # 그래도 길어지면 홀수 번째만 남긴다 ([::2] = 2칸씩 건너뛰기)
            if len(self._path) > 2000:
                self._path = self._path[::2]

    @safe
    def on_battery(self, msg):
        """BatteryState → 대기 화면의 출발 조건.

        ★ 탐험 화면에는 여전히 안 띄운다.
          탐험 중에 배터리 퍼센트가 보이면 화면이 관제 대시보드가 되어
          캐릭터가 죽는다. 대기 화면에서는 성격이 다르다 —
          '나갈 수 있는 상태인가'라는 출발 조건이라 캐릭터와 부딪히지 않는다.
          그래서 exploring.js 는 이 값을 IDLE 화면에서만 그린다.

        ★ percentage 의 단위가 드라이버마다 다르다.
          REP-147 은 0.0~1.0 인데 0~100 으로 쏘는 드라이버가 흔하다.
          turtlebot3_node 는 28.33 처럼 0~100 으로 준다.
          둘 다 받도록 해둔다. 안 그러면 87% 가 1% 로 보인다.

        ★ NaN 을 걸러야 한다.
          퍼센트를 못 재는 드라이버는 NaN 을 넣는다.
          그대로 내려보내면 json.dumps 가 NaN 을 뱉고,
          브라우저의 JSON.parse 가 통째로 터진다. WebSocket 이 죽는다.
        """
        pct = msg.percentage
        if pct is None or math.isnan(pct):
            return

        if pct <= 1.0:                  # 0.0~1.0 스케일이면 퍼센트로 바꾼다
            pct *= 100.0
        pct = max(0.0, min(100.0, float(pct)))

        # 배터리는 초당 여러 번 올 수 있다. 1 초에 한 번만 반영한다.
        # 화면이 1Hz 로 갱신되므로 더 자주 써봐야 보이지도 않는다.
        now = time.time()
        if now - self._battery_last < 1.0:
            return
        self._battery_last = now

        # power_supply_status : 1 = CHARGING, 4 = FULL
        # turtlebot3_node 는 0 (UNKNOWN) 을 주는 경우가 많다 → 충전 아님으로 본다
        charging = msg.power_supply_status in (1, 4)

        # ★ ready 를 브리지가 계산해서 내려준다.
        #   문턱값을 프론트에도 적어두면 config.py 만 고치고
        #   자바스크립트를 안 고치는 사고가 난다.
        state.patch(battery={
            "percent":   round(pct),
            "charging":  charging,
            "ready":     pct >= config.BATTERY_READY_PCT,
            "ready_pct": config.BATTERY_READY_PCT,
            "at":        time.strftime("%H:%M:%S"),
        })

    # ════════════════════════════════════════════════════════
    # 미션 · 행동
    # ════════════════════════════════════════════════════════

    @safe
    def on_mission(self, msg):
        """MissionState → 화면 라우팅.

        msg.state 값이 그대로 화면을 결정한다.
            EXPLORING  → 탐험 화면
            RETURNING  → "집으로 돌아가는 중"
            REFLECTING → "일기 쓰는 중"
            COMPLETED  → 일기 화면으로 전환

        새 session_id에서는 경로와 발견 마커를 비운다.
        SLAM 지도 자체는 유지하며 RESET 완료는 ROS 보고로 확인한다.
        """
        prev = state.snapshot()["mission"]
        if not state.apply_mission_report(msg.state, msg.session_id):
            return
        if msg.session_id != self._session_id:
            self._map_msg = None
            self._session_id = msg.session_id
            self._path.clear()
            self._markers.clear()
            self._pose = None
            self._exploring_since = None
            self._map_last = 0.0

        # EXPLORING 으로 '들어오는 순간' 시계를 새로 켠다.
        # 이미 값이 있어도 덮어쓴다 — 새 탐험이 시작된 것이므로.
        if msg.state == "EXPLORING" and prev != "EXPLORING":
            self._exploring_since = time.time()
        elif msg.state in ("IDLE", "PREPARING", "COMPLETED"):
            self._exploring_since = None

    @safe
    def on_normal(self, msg):
        data = json.loads(msg.data)
        snapshot = state.snapshot()
        if (snapshot['mission'] in ('NORMAL', 'NORMAL_STOPPING')
                and data.get('session_id') == snapshot['session_id']):
            state.patch(normal=data)

    @safe
    def on_behavior(self, msg):
        """BehaviorState → 상단 큰 문구.

        msg.behavior 를 schema.js 의 SAY 표가 사람 말로 번역한다.
            FIRST_ENCOUNTER → "처음 보는 물체 앞에 섰어요"

        msg.detail / msg.status 는 지금 쓰지 않는다.
        (필요해지면 상단 작은 글씨로 붙일 수 있다)
        """
        mode = getattr(msg, 'exploration_mode', '')
        state.patch(behavior=msg.behavior)
        if mode in ('FRONTIER', 'ROAM'):
            state.patch(explore_mode=mode)

    @safe
    def on_detections(self, msg):
        """DetectedObjectArray → "다음 차례 · bottle, backpack"

        한 장면에서 여러 물체가 잡히면 순서대로 처리하는데,
        그 대기열을 화면에 보여준다.
        맨 앞은 지금 처리 중인 것이므로 빼고, 나머지만 큐로 표시한다.
        """
        # 현재 Behavior Executor는 한 batch에서 가장 큰 물체 하나만
        # 처리하므로 나머지를 대기열처럼 표시하지 않는다.
        state.patch(queue=[])

    @safe
    def on_map(self, msg):
        """SLAM 지도. 메시지만 받아두고 변환은 타이머에서 한다."""
        if self._map_msg is None:
            self.get_logger().info(
                f"지도 수신 시작 {msg.info.width}x{msg.info.height} "
                f"res={msg.info.resolution}")
        self._map_msg = msg

    def render_map(self):
        """OccupancyGrid → PNG + 좌표 변환. on_tick 이 주기적으로 부른다."""
        if self._map_msg is None:
            return

        now = time.time()
        if now - self._map_last < config.MAP_THROTTLE_SEC:
            return
        self._map_last = now

        try:
            view = mapper.render(self._map_msg, MAP_PNG)
        except Exception as e:
            self.get_logger().error(f"지도 변환 실패: {e}")
            return

        if view is None:
            return              # 아직 아무 데도 안 가봤다

        self._map_seq += 1
        # mapper 는 [(x, y, action), …] 리스트를 기대한다.
        # 딕셔너리는 파이썬 3.7+ 에서 넣은 순서를 유지하므로
        # values() 를 그대로 넘기면 발견 순서대로 그려진다.
        state.patch(map=mapper.build_state(
            view, self._map_seq, self._path, self._pose,
            list(self._markers.values())))

    def on_tick(self):
        """1 초마다. 명령 배출 → 지도 변환 → 경과 시간.

        ★ 명령을 여기서 내보내는 이유
          웹 요청(Flask 스레드)에서 곧바로 publish 하면
          rclpy 를 두 스레드에서 동시에 만지게 된다.
          큐에 넣어두고 ROS 스레드가 꺼내 보내면 그 문제가 없다.
        """
        # 웹에서 쌓인 명령을 토픽으로 내보낸다
        for name, detail in commands.drain():
            m = String()
            m.data = f"{name}:{detail}" if detail else name
            self.pub_command.publish(m)
            self.get_logger().info(f"명령 발행 → {m.data}")

        self.render_map()

        if self._exploring_since is None:
            return
        with state.LOCK:
            state.STATE["elapsed_sec"] = int(time.time() - self._exploring_since)

    # ════════════════════════════════════════════════════════
    # 발견 3 단계 — 전부 detection_id 로 묶인다
    # ════════════════════════════════════════════════════════

    @safe
    def on_encounter(self, msg):
        """① EncounterResult — 물체를 처음 만났다.

        아직 호기심 판단 전이라 decision 은 None.
        화면에는 "저기 뭔가 있어요. 가까이 가볼게요."가 뜬다.
        """
        if not self._is_current_detection(msg.detection_id):
            return
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
        # 지도에 찍을 발견 위치. 지금 로봇이 서 있는 자리를 쓴다.
        # detection_id 를 열쇠로 넣어야 나중에 판단이 제 짝을 찾는다.
        if self._pose:
            self._markers[msg.detection_id] = (
                self._pose[0], self._pose[1], "PENDING")

        fields = {k: v for k, v in item.items() if k != "detection_id"}
        if not state.update_discovery(msg.detection_id, **fields):
            state.add_discovery(item)

    @safe
    def on_decision(self, msg):
        """② CuriosityDecision — 호기심 판단이 끝났다.

        이 필드들로 화면 문장이 생성된다 (static/js/schema.js 의 describe).
            visit_count = 0                     → "처음 보는 물체예요"
            visit_count = 3, novel = []         → "3번째 보는 거예요"
            novel = [object_condition]          → "전에도 봤는데 상태가 달라요"
            compared_record_count = 0           → "이런 건 굳이 안 봐도 돼요"

        ★ visit_count 가 .msg 에 없으면 아래 getattr 이 0 을 돌려주고
          화면에 "0번째 보는 거예요"가 뜬다. 필드 추가가 필요하다.

        ★ 이 docstring 은 함수 첫 줄에 있어야 한다.
          전에는 마커 갱신 코드 뒤에 있어서 docstring 이 아니라
          그냥 버려지는 문자열이었다. help() 에도 안 뜬다.
        """
        # 이 발견의 지도 마커에 판단 결과를 채운다.
        # OBSERVE 는 주황 큰 점, IGNORE 는 회색 작은 점으로 그려진다.
        if not self._is_current_detection(msg.detection_id):
            return
        if msg.detection_id in self._markers:
            x, y, _ = self._markers[msg.detection_id]
            self._markers[msg.detection_id] = (x, y, msg.action)

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
        # (ROS 는 토픽 간 순서를 보장하지 않는다)
        if not state.update_discovery(msg.detection_id, decision=decision):
            state.add_discovery({
                "detection_id": msg.detection_id,
                "at": time.strftime("%H:%M"),
                "observed": False,
                "photo_url": None,
                "label": {"object_name": "?"},
                "decision": decision,
            })

    @safe
    def on_observation(self, msg):
        """③ ObservationResult — 관찰이 끝났다.

        화면에서 "관찰 완료" 태그가 붙고 사진이 빠진다.
        (사진은 지금 보고 있는 물체에만 표시한다)

        msg.diary_summary 는 일기용 한 줄 요약이다.
        지금 탐험 화면에서는 안 쓰지만, DB 에 저장되면
        일기 화면에서 entries[].text 의 재료가 될 수 있다.
        """
        if not self._is_current_detection(msg.detection_id):
            return
        if not msg.success:
            self.get_logger().warn(f"observation 실패: {msg.failure_reason}")
            return

        state.update_discovery(
            msg.detection_id,
            observed=True,
            photo_url=to_web_path(msg.representative_image_path),
            label=label_to_dict(msg.detailed_label),   # 관찰 후 더 자세해진 라벨
        )

        # 관찰 개수는 브리지가 직접 센다.
        # 로봇이 따로 보내줄 필요가 없다.
        snap = state.snapshot()
        done = sum(1 for d in snap["discoveries"] if d.get("observed"))
        state.patch(observed_count=done)

    def _is_current_detection(self, detection_id):
        """Drop delayed results from an old mission after reset."""
        snapshot = state.snapshot()
        if not snapshot['session_id'] or snapshot['mission'] in ('IDLE', 'RESETTING'):
            return False
        return (
            ':' not in detection_id
            or detection_id.split(':', 1)[0] == snapshot['session_id']
        )


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
