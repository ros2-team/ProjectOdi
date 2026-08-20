"""
단일 진실 원천.

이 모듈은 아무것도 import 하지 않는다 (표준 라이브러리 제외).
의존은 한 방향으로만 흐른다:

    ros_link ─┐
    db      ──┼→  state  ←── app  →  static/
    mapper  ──┘   (쓰기)        (읽기)

app.py 가 ros_link 를 import 하거나 그 반대가 되면 순환 참조가 생기고,
더 나쁜 건 ROS 없이 웹만 테스트하는 게 불가능해진다.
"""

import copy
import threading

LOCK = threading.Lock()


def blank_state():
    """이것이 API 명세다. static/js/exploring.js 의 S 와 필드명이 1:1로 같다."""
    return {
        "mission": "EXPLORING",        # IDLE | PREPARING | EXPLORING | RETURNING | REFLECTING | COMPLETED
        "behavior": "EXPLORE",         # EXPLORE | FIRST_ENCOUNTER | EVALUATE_CURIOSITY | OBSERVE
        "explore_mode": "FRONTIER",    # FRONTIER | ROAM
        "elapsed_sec": 0,
        "motivation": 1.0,
        "observed_count": 0,
        "queue": [],                   # 같은 장면에서 같이 잡혀 대기 중인 물체
        "camera": None,                # {"url": "/media/latest.jpg?t=…", "at": "14:32"}
        "map": None,                   # {"seq", "url", "width", "height", "path", "pose", "markers"}
        "discoveries": [],             # 최신순
    }


STATE = blank_state()


# ============================================================
# 읽기 — app.py 가 쓴다
# ============================================================

def snapshot():
    """락을 짧게 잡고 복사해서 내보낸다.
    json.dumps 를 락 안에서 하면 직렬화 시간만큼 ROS 콜백이 밀린다."""
    with LOCK:
        return copy.deepcopy(STATE)


# ============================================================
# 쓰기 — ros_link.py / fake.py / db.py 가 쓴다
# ============================================================

def reset():
    with LOCK:
        STATE.clear()
        STATE.update(blank_state())


def patch(**fields):
    """STATE 최상위 필드를 갱신한다.

        patch(mission="RETURNING", behavior=None)
    """
    with LOCK:
        for k, v in fields.items():
            if v is not None:
                STATE[k] = v


def spend_motivation(amount):
    """행동으로 의욕을 소비한다. 프론트가 이 낙차를 감지해 게이지를 깜빡인다."""
    with LOCK:
        STATE["motivation"] = max(0.0, STATE["motivation"] - amount)


def add_discovery(item):
    """새 발견을 맨 앞에 넣는다 (탐험 중 화면은 최신순)."""
    with LOCK:
        STATE["discoveries"].insert(0, dict(item))


def update_discovery(detection_id, **fields):
    """이미 있는 발견을 갱신한다. 없으면 False."""
    with LOCK:
        for d in STATE["discoveries"]:
            if d.get("detection_id") == detection_id:
                d.update(fields)
                return True
    return False