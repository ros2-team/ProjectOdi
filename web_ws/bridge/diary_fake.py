"""
일기 목 데이터 — DB 가 생기기 전까지 화면을 굴리는 용도.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 파일이 곧 명세다
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

여기 있는 딕셔너리 모양이 그대로 웹으로 나간다.
나중에 bridge/db.py 가 같은 모양을 DB 에서 만들어 내면
프론트는 한 줄도 안 고치고 붙는다.

    지금 :  diary_fake.get_session(3)   ← 하드코딩
    나중 :  db.get_session(3)           ← MySQL 조회

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI 가 만들어야 하는 형식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

diary 필드가 핵심이다. 통짜 텍스트가 아니라 구조화된 JSON 이어야 한다.

    {
      "opening":  "여는 문장",
      "entries":  [ {"observation_id": 12, "text": "그 관찰에 대한 한 단락"} ],
      "closing":  "닫는 문장"
    }

★ 왜 통짜 텍스트면 안 되는가

  "오늘은 멀리 나가봤다. 병을 만났다. 화분도 있었다." 처럼 한 덩어리로 오면
  어느 문장이 어느 사진에 해당하는지 알 방법이 없다.
  그러면 글 아래에 사진을 나열할 수밖에 없는데,
  그건 일기가 아니라 첨부파일 달린 보고서다.

  entries 로 쪼개져 있으면 observation_id 로 사진을 찾아
  글 바로 위에 놓을 수 있다. 사진과 글이 1:1 로 묶인다.

★ 부수적인 이득 : 부분 실패를 견딘다

  통짜면 AI 호출이 실패했을 때 일기가 통째로 없다. 빈 화면이 나온다.
  구조화하면 entries[1] 하나가 비어도 그 블록만 사진+시각만 표시된다.
  전부 실패해도 사진과 시각을 시간순으로 나열할 수 있다 —
  글 없는 사진 일기도 일기는 된다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
★ 핵심 연결
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    _OBSERVATIONS 의  "id": 12
    diary.entries 의  "observation_id": 12

  이 둘이 같아야 static/js/diary.js 가 사진과 글을 짝짓는다.
  한쪽만 고치면 그 블록의 사진이 사라진다.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사진 경로
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  photo_url 은 tools/fake_robot.py 가 만들어 둔 파일을 가리킨다.
  그 스크립트를 한 바퀴 돌리면 static/media/obs/ 에
  obs_d2.jpg, obs_d4.jpg, obs_d5.jpg, obs_d6.jpg 가 생긴다.
  (카메라가 방금 본 화면을 복사한 것이라 실제 사진이 들어간다)

  파일이 없으면 화면에 "사진을 찾을 수 없어요" 자리만 뜬다.
"""


# ════════════════════════════════════════════════════════════
# 세션 하나 = 탐험 한 번
# ════════════════════════════════════════════════════════════

_SESSIONS = {
    3: {
        "id": 3,
        "started_at": "2026-08-26 09:58",
        "ended_at": "2026-08-26 10:01",
        "minutes": 3,

        # 왜 끝났는지. 일기의 마지막 문장이 여기서 갈린다.
        #   MOTIVATION  = 의욕을 다 써서  → "오늘은 실컷 돌아다녔다"
        #   TIME_LIMIT  = 시간이 다 돼서  → "더 보고 싶었는데 시간이 됐다"
        "ended_by": "MOTIVATION",

        "found_count": 6,      # 만난 물체 (지나친 것 포함)
        "observed_count": 4,   # 자세히 관찰한 것

        # none | generating | ready | failed
        # generating 이면 웹은 "일기 쓰는 중" 화면을 보여주고 2초마다 다시 확인한다.
        "diary_status": "ready",

        # ★ AI 가 만드는 부분
        "diary": {
            "opening": "오늘은 평소보다<br>조금 더 멀리 나가봤다.",
            "entries": [
                {"observation_id": 12,
                 "text": "투명한 병이 바닥에 놓여 있었다. 표면이 매끈하고 빛이 통과했다. "
                         "지난번에 본 것과 비슷한 줄 알았는데, 가까이서 보니 완전히 "
                         "다른 물건이었다."},
                {"observation_id": 14,
                 "text": "구석에 놓인 화분은 전에도 본 적이 있다. 그런데 오늘은 잎이 "
                         "축 늘어져 있었다. 지난번엔 이렇지 않았는데."},
                {"observation_id": 15,
                 "text": "책상 위에 컵이 하나 있었다. 손잡이가 달려 있고 파란 무늬가 "
                         "그려져 있었다. 안에는 아무것도 들어 있지 않았다."},
                {"observation_id": 16,
                 "text": "가방을 다시 만났다. 지난번과 같은 자리인데 겉 재질이 달라 "
                         "보였다. 한 바퀴 돌면서 봤지만 열려 있진 않았다."},
            ],
            "closing": "돌아오는 길은 금방이었다.<br>오늘은 실컷 돌아다녔다.",
        },
    },

    # 발견 0 개로 끝난 경우 — 최대 시간 초과 시 충분히 생긴다.
    # 빈 화면 대신 짧은 일기를 주면 실패처럼 안 보이고 오히려 캐릭터가 산다.
    2: {
        "id": 2,
        "started_at": "2026-08-25 16:10",
        "ended_at": "2026-08-25 16:15",
        "minutes": 5,
        "ended_by": "TIME_LIMIT",
        "found_count": 2,
        "observed_count": 0,
        "diary_status": "ready",
        "diary": {
            "opening": "오늘은 새로운 걸<br>만나지 못했다.",
            "entries": [],
            "closing": "아는 길만 계속 돌았다.<br>내일은 다른 쪽으로 가봐야지.",
        },
    },
}


# ════════════════════════════════════════════════════════════
# 관찰 기록 — observations 테이블에 해당
#
# tools/fake_robot.py 의 시나리오와 같은 물체·순서다.
# 탐험 화면에서 본 것이 일기에도 그대로 나와야 이야기가 이어진다.
#
# ★ 지나친 것(IGNORE)도 반드시 남긴다.
#   일기 아래쪽에 "그 밖에 chair와 person도 지나쳤지만" 한 줄로 들어간다.
#   지워버리면 "골라서 봤다"는 게 사라지고, Odi 가 눈에 띄는 걸
#   다 찍는 로봇으로 보인다.
# ════════════════════════════════════════════════════════════

_OBSERVATIONS = {
    3: [
        # ① chair — 3번째 보는 물건이라 지나쳤다
        {
            "id": 11, "session_id": 3, "at": "09:58",
            "label": {"object_name": "chair", "object_primary_color": "검정",
                      "object_secondary_color": "회색", "object_material": "플라스틱",
                      "object_shape": "각진", "object_condition": "깨끗함"},
            "decision": {"action": "IGNORE", "curiosity_score": 0.18,
                         "similarity_score": 0.91, "novel_features": [],
                         "duplicated_features": ["object_material"],
                         "visit_count": 3, "compared_record_count": 12},
            "photo_url": None,      # 지나친 건 일기에 사진을 안 쓴다
            "observed": False,
        },

        # ② bottle — 처음 보는 물건이라 관찰했다
        {
            "id": 12, "session_id": 3, "at": "09:59",
            "label": {"object_name": "bottle", "object_primary_color": "투명",
                      "object_secondary_color": "파랑", "object_material": "유리",
                      "object_shape": "원통", "object_condition": "깨끗함"},
            "decision": {"action": "OBSERVE", "curiosity_score": 0.81,
                         "similarity_score": 0.42,
                         "novel_features": ["object_material", "object_primary_color"],
                         "duplicated_features": [],
                         "visit_count": 0, "compared_record_count": 12},
            "photo_url": "/media/obs/obs_d2.jpg",
            "observed": True,
        },

        # ③ person — IGNORE_CLASSES 로 걸러졌다 (compared_record_count 0)
        {
            "id": 13, "session_id": 3, "at": "09:59",
            "label": {"object_name": "person", "object_primary_color": "",
                      "object_secondary_color": "", "object_material": "",
                      "object_shape": "", "object_condition": ""},
            "decision": {"action": "IGNORE", "curiosity_score": 0.0,
                         "similarity_score": 0.0, "novel_features": [],
                         "duplicated_features": [],
                         "visit_count": 0, "compared_record_count": 0},
            "photo_url": None,
            "observed": False,
        },

        # ④ plant — 전에 봤는데 상태가 달라졌다
        {
            "id": 14, "session_id": 3, "at": "10:00",
            "label": {"object_name": "plant", "object_primary_color": "초록",
                      "object_secondary_color": "갈색", "object_material": "흙",
                      "object_shape": "갈라진", "object_condition": "시듦"},
            "decision": {"action": "OBSERVE", "curiosity_score": 0.67,
                         "similarity_score": 0.88,
                         "novel_features": ["object_condition"],
                         "duplicated_features": ["object_name"],
                         "visit_count": 2, "compared_record_count": 14},
            "photo_url": "/media/obs/obs_d4.jpg",
            "observed": True,
        },

        # ⑤ cup — 처음 보는 물건
        {
            "id": 15, "session_id": 3, "at": "10:00",
            "label": {"object_name": "cup", "object_primary_color": "흰색",
                      "object_secondary_color": "파랑", "object_material": "도자기",
                      "object_shape": "원통", "object_condition": "깨끗함"},
            "decision": {"action": "OBSERVE", "curiosity_score": 0.88,
                         "similarity_score": 0.31, "novel_features": [],
                         "duplicated_features": [],
                         "visit_count": 0, "compared_record_count": 15},
            "photo_url": "/media/obs/obs_d5.jpg",
            "observed": True,
        },

        # ⑥ backpack — 전에 봤는데 재질이 다르다
        {
            "id": 16, "session_id": 3, "at": "10:01",
            "label": {"object_name": "backpack", "object_primary_color": "회색",
                      "object_secondary_color": "검정", "object_material": "천",
                      "object_shape": "둥근", "object_condition": "낡음"},
            "decision": {"action": "OBSERVE", "curiosity_score": 0.72,
                         "similarity_score": 0.85,
                         "novel_features": ["object_material"],
                         "duplicated_features": ["object_name", "object_shape"],
                         "visit_count": 1, "compared_record_count": 16},
            "photo_url": "/media/obs/obs_d6.jpg",
            "observed": True,
        },
    ],

    2: [
        {
            "id": 8, "session_id": 2, "at": "16:11",
            "label": {"object_name": "chair", "object_primary_color": "검정",
                      "object_secondary_color": "", "object_material": "플라스틱",
                      "object_shape": "각진", "object_condition": "깨끗함"},
            "decision": {"action": "IGNORE", "curiosity_score": 0.15,
                         "similarity_score": 0.93, "novel_features": [],
                         "duplicated_features": ["object_name"],
                         "visit_count": 2, "compared_record_count": 9},
            "photo_url": None, "observed": False,
        },
        {
            "id": 9, "session_id": 2, "at": "16:13",
            "label": {"object_name": "door", "object_primary_color": "흰색",
                      "object_secondary_color": "", "object_material": "나무",
                      "object_shape": "각진", "object_condition": "깨끗함"},
            "decision": {"action": "IGNORE", "curiosity_score": 0.09,
                         "similarity_score": 0.96, "novel_features": [],
                         "duplicated_features": ["object_name"],
                         "visit_count": 6, "compared_record_count": 10},
            "photo_url": None, "observed": False,
        },
    ],
}


# ════════════════════════════════════════════════════════════
# 조회 함수 — bridge/db.py 가 같은 이름으로 대체한다
# ════════════════════════════════════════════════════════════

def list_sessions():
    """지난 일기 목록. 시작 화면과 /diary 에서 쓴다. 최신순."""
    out = []
    for s in sorted(_SESSIONS.values(), key=lambda x: x["id"], reverse=True):
        d = s.get("diary") or {}
        # 목록에는 여는 문장만 한 줄로 보여준다.
        # <br> 은 목록에서 줄바꿈이 되면 안 되므로 공백으로 바꾼다.
        line = (d.get("opening") or "").replace("<br>", " ")
        out.append({
            "id": s["id"],
            "date": s["started_at"][5:10].replace("-", "."),   # "08.26"
            "line": line,
            "date_full": s["started_at"][:10].replace("-", "."),
            "photo_url": next((o["photo_url"] for o in get_observations(s["id"])
                               if o.get("observed") and o.get("photo_url")), None),
            "observed_count": s["observed_count"],
        })
    return out


def get_session(session_id):
    """세션 하나. 없으면 None."""
    return _SESSIONS.get(int(session_id))


def get_observations(session_id):
    """그 세션의 관찰 기록 전부. 시간순(오래된 것부터).

    ★ 탐험 화면과 정렬 방향이 반대다.
      탐험 중  : 최신순 — 지금 뭘 하는지가 맨 위에 있어야 한다
      일기     : 시간순 — 이야기는 순서대로 읽혀야 한다
      같은 데이터인데 화면 성격이 달라서 그렇다.
    """
    return sorted(_OBSERVATIONS.get(int(session_id), []), key=lambda o: o["id"])
