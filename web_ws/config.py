"""설정을 한 곳에 모은다. 발표 직전에 바꿀 값들은 전부 여기 있어야 한다."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# ── 서버 ────────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8000
PUSH_HZ = 1.0          # 상태 푸시 주기. 1~2Hz면 충분하다.

# ── 1단계: 가짜 시나리오 ─────────────────────────────────
# ROS를 붙이면 False. 그때 bridge/fake.py 를 지운다.
USE_FAKE = False
FAKE_LOOP_SEC = 240    # 리허설용으로 이 시간마다 처음부터 되감는다

# ── 2단계: ROS ──────────────────────────────────────────
# 지금 실제로 퍼블리시되는 토픽 (ros2 topic list 로 확인)
TOPIC_CAMERA = "/camera/image_raw/compressed"
TOPIC_ODOM = "/odom"
TOPIC_BATTERY = "/battery_state"
TOPIC_SCAN = "/scan"

STREAM_FPS = 12              # 브라우저로 내보낼 상한. 16fps 원본을 다 보내면
                            # 클라이언트당 0.5MB/s 라 와이파이가 버겁다
DISK_SAVE_SEC = 1.0         # latest.jpg 저장 주기. 일기용 사진은 이걸로 충분

# 아직 없는 토픽 — 팀에 요청 필요.
# CuriosityDecision 은 지금 /curiosity/evaluate 서비스 응답으로만 나가서
# 브리지가 받을 수 없다. 미션 노드가 결과를 토픽으로 한 번 더 쏴줘야 한다.
TOPIC_MISSION = "/odi/mission_state"
TOPIC_DISCOVERY = "/odi/discovery"
TOPIC_MAP = "/map"           # SLAM 이 뜨면 생긴다

# ── 3단계: DB ───────────────────────────────────────────
# 브리지는 detected_objects 를 읽기만 한다.
# 쓰는 건 세션 테이블뿐. 호기심 노드와 커넥션을 공유하지 않는다.
DB = {
    "host": "192.168.0.20",
    "port": 3306,
    "user": "yyj",
    "password": "1234",
    "database": "Odi_DB",
}

# ── 5단계: 지도 ─────────────────────────────────────────
MAP_THROTTLE_SEC = 3.0   # PNG 재생성 간격. 1초마다 만들 필요 없다.
MAP_CROP_MARGIN = 10     # 미탐색 영역을 잘라낼 때 남길 여백 (셀)