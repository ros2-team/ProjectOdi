"""설정을 한 곳에 모은다. 발표 직전에 바꿀 값들은 전부 여기 있어야 한다."""

# ┌─ 연결 지도 ────────────────────────────────────────────────
# │ 이 파일은 아무것도 import 하지 않는다. 값만 있다.
# │
# │ 이 파일을 읽어가는 곳 :
# │     run.py       → USE_FAKE, HOST, PORT
# │     app.py       → STATIC_DIR, PUSH_HZ, STREAM_FPS
# │     ros_link.py  → TOPIC_* , DISK_SAVE_SEC
# │     fake.py      → FAKE_LOOP_SEC
# │
# │ 발표 직전에 바꿀 값은 전부 여기 모여 있다.
# └────────────────────────────────────────────────────────────

from pathlib import Path

# 파일 경로 기준 기본 디렉토리 설정
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"  # 웹 정적 파일(HTML, CSS, JS) 위치

# ── 서버 설정 ────────────────────────────────────────────
HOST = "0.0.0.0"  # 외부 모든 IP 접근 허용
PORT = 8000  # 웹 서버 포트 번호
PUSH_HZ = 1.0  # WebSocket으로 웹 화면에 상태 정보를 보낼 주기 (초당 1회)

# ── 1단계: 가짜 테스트 모드 ────────────────────────────────
USE_FAKE = False  # True면 로봇(ROS) 없이 가짜 데이터로 테스트, False면 실제 로봇 연결
FAKE_LOOP_SEC = 240  # 테스트 시 리허설용 자동 되돌리기 시간(초)

# ── 2단계: 실제 ROS2 토픽 이름 ────────────────────────────
# 지금 실제로 발행 중인 것 (ros2 topic list 로 확인함)
TOPIC_CAMERA = "/camera/image_raw/compressed"  # 카메라 영상 토픽
TOPIC_ODOM = "/odom"  # 로봇 주행 위치(오도메트리) 토픽
TOPIC_BATTERY = "/battery_state"  # 배터리 잔량 토픽
TOPIC_SCAN = "/scan"  # 라이다 스캔 데이터

STREAM_FPS = 12  # 웹 브라우저 카메라 스트리밍 최대 프레임 (네트워크 과부하 방지용 *16으로하면터짐..)
DISK_SAVE_SEC = 1.0  # 일기 작성에 쓰일 최신 카메라 이미지를 파일로 저장하는 주기(초)

# ── 팀원이 추가 개발 후 발행해야 할 토픽 6개 ────────────────
# 메시지 타입은 이미 odi_interfaces 에 전부 정의되어 있다. 발행만 하면 된다.
#
# EncounterResult / ObservationResult 는 액션 result 이고,
# CuriosityDecision 은 서비스 응답이라서 브리지가 직접 못 받는다.
# 액션 result 와 서비스 응답은 요청한 노드에게만 가기 때문이다.
# → 미션 노드가 받아서 토픽으로 재발행해야 한다. (docs/토픽요청.md 참조)
TOPIC_MISSION = "/odi/mission_state"                # MissionState        화면 라우팅
TOPIC_BEHAVIOR = "/odi/behavior_state"              # BehaviorState       상단 큰 문구
TOPIC_DETECTIONS = "/odi/detections"                # DetectedObjectArray 다음 차례 큐
#TOPIC_ENCOUNTER = "/perception/scene_data_1st"      # EncounterResult     ① 처음 만남
TOPIC_DECISION = "/odi/curiosity_decision"          # CuriosityDecision   ② 호기심 판단
#TOPIC_OBSERVATION = "/perception/scene_data_2nd"    # ObservationResult   ③ 관찰 완료
TOPIC_ENCOUNTER = "/odi/encounter"        # 로봇 팀이 EncounterResult 로 새로 발행
TOPIC_OBSERVATION = "/odi/observation"    # 로봇 팀이 ObservationResult 로 새로 발행

TOPIC_MAP = "/map"  # SLAM 지도 데이터

# 웹 → 로봇 명령. std_msgs/String 으로 "START" 를 보낸다.
# ★ 로봇 팀은 이 토픽만 구독하면 된다. 커스텀 메시지 필요 없음.
TOPIC_COMMAND = "/odi/command"

# 로봇이 관찰 사진을 저장하는 폴더.
# 웹은 이 폴더를 /media/obs/파일명 으로 서빙한다.
# 로봇이 다른 폴더에 저장하면 심볼릭 링크를 걸거나 이 값을 맞춘다.
PHOTO_DIR = STATIC_DIR / "media" / "obs"

# ── 3단계: 데이터베이스 설정 ──────────────────────────────
# 브리지는 detected_objects 를 읽기만 한다. 쓰는 건 세션 테이블뿐.
# 호기심 노드와 커넥션을 공유하지 않는다.
DB = {
    "host": "192.168.0.20",
    "port": 3306,
    "user": "yyj",
    "password": "1234",
    "database": "Odi_DB",
}

# ── 5단계: 지도 관련 설정 ────────────────────────────────
MAP_THROTTLE_SEC = 2.0  # 지도 PNG 이미지 재생성 간격
MAP_CROP_MARGIN = 10  # 미탐색 영역을 잘라낼 때 남길 여백 크기 (셀)

# 이 퍼센트 미만이면 대기 화면의 시작 버튼이 잠긴다.
# 발표 직전에 배터리가 애매하면 여기를 낮춘다.
BATTERY_READY_PCT = 20