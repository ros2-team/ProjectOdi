from . import weights as W


class CuriosityPolicy:
    """
    최종 호기심 점수로 로봇의 행동을 결정한다.

    출력은 반드시 'OBSERVE' 또는 'IGNORE' 두 가지뿐이다.
    메인(Behavior Executor)이 이 문자열로 분기하므로
    임의의 값을 내보내면 관찰 단계가 실행되지 않는다.
    """
    
    def decide_action(self, score: float) -> str:
        if score >= W.TH_OBSERVE:
            return 'OBSERVE'   # 접근해서 정밀 관찰
        return 'IGNORE'        # 추가 관찰 없이 탐험 계속