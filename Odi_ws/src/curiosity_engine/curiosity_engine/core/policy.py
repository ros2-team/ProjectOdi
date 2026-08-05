from . import weights # 임계값 설정을 위한 임포트 

class CuriosityPolicy:
    def decide_action(self, score: float) -> str:
        if score >= weights.THRESHOLD_APPROACH:
            return "APPROACH_AND_INSPECT"  # 점수 높음 : 접근 탐색 
        elif score >= weights.THRESHOLD_OBSERVE:
            return "OBSERVE_FROM_DISTANCE"  # 점수 보통 : 멀리서 관차ㅓㅇ 
        else:
            return "IGNORE"  # 점수 낮음 : 무시 