class CuriosityPolicy:
    """
    최종 호기심 점수 구간별 로봇의 행동(Decision)을 결정하는 정책 클래스
    """

    def decide_action(self, score: float) -> str:
        if score >= 0.8:
            return "APPROACH_AND_INSPECT"  # 점수 0.8 이상: 다가가서 정밀 조사
        elif score >= 0.6:
            return "OBSERVE_FROM_DISTANCE" # 점수 0.6 이상 ~ 0.8 미만: 원거리에서 관찰
        elif score >= 0.4:
            return "STOP_AND_CAPTURE"      # 점수 0.4 이상 ~ 0.6 미만: 정지 후 사진/데이터 캡처
        elif score >= 0.2:
            return "GLANCE"                # 점수 0.2 이상 ~ 0.4 미만: 흘끗 쳐다보고 이동
        else:
            return "IGNORE"                # 점수 0.2 미만: 무시