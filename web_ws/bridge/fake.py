"""
1단계 전용 가짜 시나리오.

2단계에서 이 파일을 지우고 bridge/ros_link.py 로 교체한다.
시나리오가 서버에만 있는 게 중요하다 — 프론트에도 복사해두면
문구나 흐름을 고칠 때 한쪽만 고치고 넘어가게 된다.
"""

import time

import config
from bridge import state


def lab(name, primary, secondary, material, shape, condition):
    """SemanticLabel 과 같은 모양"""
    return {
        "object_name": name,
        "object_primary_color": primary,
        "object_secondary_color": secondary,
        "object_material": material,
        "object_shape": shape,
        "object_condition": condition,
    }


def dec(action, score, similarity, novel, duplicated, visits, compared):
    """CuriosityDecision 과 같은 모양.

    visit_count 는 .msg 에 추가해야 한다.
    지금은 reason 문자열 안에 Visits=3 으로만 들어 있어서,
    없으면 프론트에 'undefined번째 보는 거예요' 가 뜬다.
    """
    return {
        "action": action,
        "curiosity_score": score,
        "similarity_score": similarity,
        "novel_features": novel,
        "duplicated_features": duplicated,
        "visit_count": visits,
        "compared_record_count": compared,
    }


SCRIPT = [
    {"t": 1, "behavior": "EXPLORE"},

    # 한 장면에서 chair / bottle / backpack 세 개가 동시에 잡힌다 (문서 2-4)
    {"t": 14, "behavior": "FIRST_ENCOUNTER", "queue": ["bottle", "backpack"],
     "add": {"detection_id": "d1", "at": "14:29", "observed": False, "decision": None,
             "label": lab("chair", "검정", "회색", "플라스틱", "각진", "깨끗함")}},
    {"t": 26, "behavior": "EVALUATE_CURIOSITY"},
    {"t": 36, "behavior": "FIRST_ENCOUNTER", "queue": ["backpack"],
     "set": ("d1", {"decision": dec("IGNORE", 0.18, 0.91, [], ["object_material"], 3, 12)}),
     "add": {"detection_id": "d2", "at": "14:30", "observed": False, "decision": None,
             "label": lab("bottle", "투명", "파랑", "유리", "원통", "깨끗함")}},

    {"t": 48, "behavior": "EVALUATE_CURIOSITY"},
    {"t": 58, "behavior": "OBSERVE", "spend": 0.05,
     "set": ("d2", {"decision": dec("OBSERVE", 0.81, 0.42,
                                    ["object_material", "object_primary_color"], [], 0, 12)})},
    {"t": 84, "behavior": "FIRST_ENCOUNTER", "observed": 1, "queue": [], "spend": 0.14,
     "set": ("d2", {"observed": True}),
     "add": {"detection_id": "d3", "at": "14:32", "observed": False, "decision": None,
             "label": lab("backpack", "회색", "검정", "천", "둥근", "낡음")}},

    {"t": 98, "behavior": "OBSERVE", "spend": 0.05,
     "set": ("d3", {"decision": dec("OBSERVE", 0.94, 0.21, [], [], 0, 13)})},
    {"t": 124, "behavior": "EXPLORE", "observed": 2, "mode": "ROAM", "spend": 0.14,
     "set": ("d3", {"observed": True})},

    # 사람은 IGNORE_CLASSES 로 걸러진다 → compared_record_count 0
    {"t": 142, "behavior": "FIRST_ENCOUNTER",
     "add": {"detection_id": "d4", "at": "14:35", "observed": False, "decision": None,
             "label": lab("person", "", "", "", "", "")}},
    {"t": 150, "behavior": "EXPLORE",
     "set": ("d4", {"decision": dec("IGNORE", 0.0, 0.0, [], [], 0, 0)})},

    # 전에 본 화분인데 상태가 달라졌다 — get_memory_from_db 의 '최신 기록' 비교가 살아나는 케이스
    {"t": 164, "behavior": "FIRST_ENCOUNTER",
     "add": {"detection_id": "d5", "at": "14:37", "observed": False, "decision": None,
             "label": lab("plant", "초록", "갈색", "흙", "갈라진", "시듦")}},
    {"t": 176, "behavior": "OBSERVE", "spend": 0.05,
     "set": ("d5", {"decision": dec("OBSERVE", 0.67, 0.88,
                                    ["object_condition"], ["object_name"], 2, 14)})},
    {"t": 196, "behavior": "EXPLORE", "observed": 3, "spend": 0.14,
     "set": ("d5", {"observed": True})},

    {"t": 212, "mission": "RETURNING"},
]

DRAIN = 0.0022      # 초당 기본 의욕 소모. 행동할 때 spend 로 뭉텅 더 깎인다.


def apply_event(e):
    if "mission" in e:
        state.patch(mission=e["mission"])
    if "behavior" in e:
        state.patch(behavior=e["behavior"])
    if "mode" in e:
        state.patch(explore_mode=e["mode"])
    if "queue" in e:
        with state.LOCK:
            state.STATE["queue"] = e["queue"]
    if "observed" in e:
        state.patch(observed_count=e["observed"])
    if "spend" in e:
        state.spend_motivation(e["spend"])
    if "add" in e:
        state.add_discovery(e["add"])
    if "set" in e:
        detection_id, fields = e["set"]
        state.update_discovery(detection_id, **fields)


def loop():
    """★ 2단계에서 이 함수 자리에 rclpy 스레드가 들어간다.

        def on_mission_state(msg):
            state.patch(mission=msg.mission_state, behavior=msg.behavior)

        def ros_thread():
            rclpy.init()
            rclpy.spin(OdiBridgeNode())
    """
    step = 0
    while True:
        time.sleep(1.0)

        with state.LOCK:
            state.STATE["elapsed_sec"] += 1
            elapsed = state.STATE["elapsed_sec"]
        state.spend_motivation(DRAIN)

        while step < len(SCRIPT) and SCRIPT[step]["t"] <= elapsed:
            apply_event(SCRIPT[step])
            step += 1

        if elapsed > config.FAKE_LOOP_SEC:
            state.reset()
            step = 0