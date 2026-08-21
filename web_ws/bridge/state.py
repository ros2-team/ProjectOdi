"""
공유 상태 — 이 프로그램의 단일 진실 원천(single source of truth).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 모듈이 하는 일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"Odi 가 지금 어떤 상태인가"를 딕셔너리 하나에 담아둔다.
로봇 쪽 코드가 여기에 쓰고, 웹 쪽 코드가 여기서 읽는다. 그게 전부다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
왜 이 파일은 아무것도 import 하지 않는가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

의존 방향을 한쪽으로만 흐르게 하기 위해서다.

    ros_link ─┐
    fake    ──┼──▶  state  ◀──  app
    db      ──┘     (쓰기)      (읽기)

이 규칙이 실제로 주는 이득 :

  1) app.py 가 ros_link 를 import 하면, rclpy 가 없는 컴퓨터에서
     웹 서버가 아예 안 뜬다. 우리는 1단계에서 로봇 없이 화면을
     전부 완성했는데, 그게 가능했던 이유가 이 구조다.

  2) ros_link 가 app 을 import 하면 순환 참조(circular import)가
     생겨서 파이썬이 import 자체를 실패한다.

  3) 지금 구조에서는 ros_link.py 가 통째로 터져도 웹 서버는 살아있다.
     화면은 마지막 상태를 유지하고 "연결 끊김" 배너가 뜬다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
왜 락(Lock)이 필요한가
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

이 프로그램 안에서 스레드가 최소 셋 돌고 있다.

    (1) 메인 스레드      — Flask 웹 서버
    (2) ROS 스레드       — rclpy.spin(). 토픽 콜백이 여기서 실행됨
    (3) WebSocket 스레드 — 접속한 브라우저 하나당 하나씩

이들이 전부 아래 STATE 딕셔너리를 동시에 만진다.
락이 없으면 이런 사고가 난다.

    WebSocket 스레드 : STATE 를 JSON 으로 변환 중... discoveries 순회 중
    ROS 스레드       : 마침 discoveries 에 새 항목 insert
    WebSocket 스레드 : RuntimeError: dictionary changed size during iteration

파이썬은 순회 중에 크기가 바뀌면 예외를 던진다.
락은 "내가 만지는 동안 아무도 건드리지 마"라고 선언하는 장치다.
"""

# ┌─ 연결 지도 ────────────────────────────────────────────────
# │ ★ 이 파일은 아무것도 import 하지 않는다 (표준 라이브러리 제외).
# │   모든 파일이 이쪽으로 화살표를 쏘고, 이쪽은 아무 데도 안 쏜다.
# │
# │ 여기에 쓰는 파일 :
# │     ros_link.py  patch / add_discovery / update_discovery
# │     fake.py      patch / add_discovery / spend_motivation
# │
# │ 여기서 읽는 파일 :
# │     app.py       snapshot()  →  WebSocket  →  브라우저
# │
# │ ★ blank_state() 의 키 이름 = static/js/exploring.js 의 S 객체
# │   한쪽만 바꾸면 에러 없이 화면만 조용히 안 바뀐다.
# └────────────────────────────────────────────────────────────

import copy
import threading

# threading.Lock() 은 열쇠가 하나뿐인 방이라고 생각하면 된다.
# with LOCK: 블록에 들어가려면 열쇠를 가져야 하고,
# 다른 스레드가 이미 갖고 있으면 놓을 때까지 기다린다.
LOCK = threading.Lock()


def blank_state():
    """초기 상태를 만든다.

    ★ 이 딕셔너리의 키 이름이 곧 API 명세다.
      static/js/exploring.js 의 S 객체와 이름이 1:1 로 같아야 한다.
      한쪽만 고치면 화면이 조용히 안 바뀐다 — 에러도 안 나서 찾기 어렵다.

    ★ 상수가 아니라 함수인 이유
      상수로 두면 reset() 할 때마다 같은 리스트를 재사용하게 되어
      이전 탐험의 discoveries 가 그대로 남는다.
      호출할 때마다 새 객체를 만들어야 안전하다.
    """
    return {
        # 미션 상태 — 화면 라우팅을 결정한다.
        # IDLE | PREPARING | EXPLORING | RETURNING | REFLECTING | COMPLETED
        "mission": "EXPLORING",

        # 지금 하고 있는 행동. 화면 상단의 큰 문구가 여기서 나온다.
        # EXPLORE | FIRST_ENCOUNTER | EVALUATE_CURIOSITY | OBSERVE
        "behavior": "EXPLORE",

        # 탐험 방식. FRONTIER = 미탐색 경계로 이동, ROAM = 자유 배회
        "explore_mode": "FRONTIER",

        # 이번 탐험 번호. Explore.action 의 goal 필드와 같은 값(string).
        # 탐험이 끝나면 웹이 /diary/{session_id} 로 이동한다.
        "session_id": "",

        "elapsed_sec": 0,      # 탐험 시작부터 흐른 초
        "motivation": 1.0,     # 의욕 0.0 ~ 1.0. 0 이 되면 복귀
        "observed_count": 0,   # 지금까지 관찰을 마친 물체 수

        # 같은 장면에서 함께 탐지돼 순서를 기다리는 물체 이름들
        # 예: ["bottle", "backpack"]  → 화면에 "다음 차례 · bottle, backpack"
        "queue": [],

        # 카메라 생존 표시. {"live": True, "at": "10:34:12"}
        # ★ 이미지 자체는 여기 안 넣는다. 이유는 frames.py 주석 참조.
        "camera": None,

        # 지도. {"seq", "url", "width", "height", "path", "pose", "markers"}
        "map": None,

        # 발견 목록. 최신순 — 맨 앞이 가장 최근
        "discoveries": [],
    }


# 프로그램이 살아있는 동안 유지되는 실제 상태
STATE = blank_state()


# ════════════════════════════════════════════════════════════
# 읽기 — app.py 가 쓴다
# ════════════════════════════════════════════════════════════

def snapshot():
    """현재 상태를 복사해서 돌려준다.

    ★ 왜 STATE 를 그대로 반환하지 않고 복사하는가
      반환한 뒤에도 ROS 스레드는 STATE 를 계속 고친다.
      호출한 쪽이 그걸 JSON 으로 바꾸는 도중에 내용이 바뀌면 터진다.
      복사본을 주면 그 뒤로 무슨 일이 일어나든 안전하다.

    ★ 왜 copy.deepcopy 인가
      dict(STATE) 같은 얕은 복사는 최상위만 복사한다.
      discoveries 리스트는 원본과 같은 객체를 가리키므로
      여전히 동시 수정 위험이 남는다.
      deepcopy 는 안쪽 리스트/딕셔너리까지 전부 새로 만든다.

    ★ 왜 json.dumps 를 여기서 하지 않는가
      직렬화는 수 밀리초가 걸린다. 그동안 락을 잡고 있으면
      ROS 콜백이 전부 대기한다. 카메라가 16fps 면 프레임이 밀린다.
      복사만 하고 락을 놓은 뒤, 호출한 쪽이 락 밖에서 직렬화한다.
      → 락은 최대한 짧게 잡는다. 동시성 프로그래밍의 기본 원칙.
    """
    with LOCK:
        return copy.deepcopy(STATE)


# ════════════════════════════════════════════════════════════
# 쓰기 — ros_link.py / fake.py 가 쓴다
# ════════════════════════════════════════════════════════════

def reset():
    """상태를 초기값으로 되돌린다. 새 탐험을 시작할 때 호출.

    ★ STATE = blank_state() 라고 쓰면 안 되는 이유
      그건 이 모듈의 STATE 라는 '이름'이 새 딕셔너리를 가리키게 할 뿐이다.
      다른 모듈이 이미 import 해 간 옛 딕셔너리는 그대로 남아서,
      그쪽에서는 초기화가 안 된 것처럼 보인다.
      clear() + update() 로 '같은 객체의 내용'을 바꿔야 모두에게 반영된다.
    """
    with LOCK:
        STATE.clear()
        STATE.update(blank_state())


def patch(**fields):
    """최상위 필드 여러 개를 한 번에 갱신한다.

        patch(mission="RETURNING", motivation=0.3)

    ** 는 키워드 인자를 딕셔너리로 모아주는 파이썬 문법이다.
    patch(a=1, b=2) 로 부르면 함수 안에서 fields == {"a": 1, "b": 2} 가 된다.

    None 인 값은 무시한다. 덕분에 호출하는 쪽에서
    '값이 있으면 갱신, 없으면 그대로' 를 따로 if 없이 쓸 수 있다.
    """
    with LOCK:
        for k, v in fields.items():
            if v is not None:
                STATE[k] = v


def spend_motivation(amount):
    """의욕을 소비한다.

    화면의 게이지가 이 낙차를 감지해서 한 번 깜빡인다.
    (exploring.js 가 이전 값과 비교해 0.02 이상 떨어지면 pulse 를 켠다)

    max(0.0, ...) 로 음수를 막는다.
    게이지 width 가 음수 퍼센트가 되면 CSS 가 이상해진다.
    """
    with LOCK:
        STATE["motivation"] = max(0.0, STATE["motivation"] - amount)


def add_discovery(item):
    """새로 발견한 물체를 목록 맨 앞에 넣는다.

    ★ append 가 아니라 insert(0, ...) 인 이유
      탐험 중 화면은 최신순으로 보여준다. 지금 처리 중인 물체가
      항상 화면 맨 위에 있어야 한다. 오래된 순으로 쌓으면
      진행 중인 게 계속 화면 밖으로 밀려나서, 실시간인데 실시간이 안 보인다.

    ★ dict(item) 으로 복사하는 이유
      호출한 쪽이 나중에 그 딕셔너리를 고쳐도
      STATE 안의 것은 영향받지 않게 하기 위해서다.
    """
    with LOCK:
        STATE["discoveries"].insert(0, dict(item))


def update_discovery(detection_id, **fields):
    """이미 있는 발견의 내용을 갱신한다.

    ★ 왜 이 함수가 필요한가
      물체 하나가 여러 번에 걸쳐 갱신되기 때문이다.

        (1) 처음 만남      → decision 없이 label 만
        (2) 호기심 판단 끝 → decision 채워짐
        (3) 관찰 끝        → observed = True, 사진 경로

      같은 detection_id 로 세 번 오고, 그때마다 기존 항목을 찾아
      덮어쓴다. 매번 새로 추가하면 같은 물체가 화면에 세 번 나타난다.

    ★ 반환값
      True  = 찾아서 갱신함
      False = 그런 detection_id 가 없음

      이 반환값 덕분에 ros_link 에서 두 줄로 처리된다.

          if not state.update_discovery(id, **fields):
              state.add_discovery(item)
    """
    with LOCK:
        for d in STATE["discoveries"]:
            if d.get("detection_id") == detection_id:
                d.update(fields)
                return True
    return False