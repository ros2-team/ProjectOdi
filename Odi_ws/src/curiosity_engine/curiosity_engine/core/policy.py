from . import weights as W


class CuriosityPolicy:
    """
    최종 호기심 점수로 로봇의 행동을 결정한다.

    출력은 반드시 'OBSERVE' 또는 'IGNORE' 두 가지뿐이다.
    메인이 이 문자열로 분기하므로 임의의 값을 내보내면
    관찰 단계가 실행되지 않는다.
    """

    def decide_action(self, score: float) -> str:
        if score >= W.TH_OBSERVE:
            return 'OBSERVE'   # 접근해서 정밀 관찰
        return 'IGNORE'        # 추가 관찰 없이 탐험 계속




# from . import weights as W


# class CuriosityPolicy:
#     """
#     최종 호기심 점수 구간별 로봇의 행동(Decision)을 결정하는 정책 클래스.

#     임계값은 weights.py에서 읽는다.
#     점수 설계와 임계값은 항상 한 세트로 움직여야 하므로 
#     같은 파일에서 관리한다.
#     """

#     def decide_action(self, score: float) -> str:
#         if score >= W.TH_APPROACH:
#             return 'APPROACH_AND_INSPECT'   # 다가가서 정밀 조사
#         elif score >= W.TH_OBSERVE:
#             return 'OBSERVE_FROM_DISTANCE'  # 원거리에서 관찰
#         elif score >= W.TH_CAPTURE:
#             return 'STOP_AND_CAPTURE'       # 정지 후 촬영
#         elif score >= W.TH_GLANCE:
#             return 'GLANCE'                 # 흘끗 보고 이동
#         else:
#             return 'IGNORE'                 # 무시