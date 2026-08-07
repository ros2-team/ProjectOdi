from .data_models import ObjectCandidate, MemoryInfo
from . import weights

class CuriosityCalculator:
    """
    객체 정보와 DB 기억 정보를 비교하여 호기심 점수를 산출하는 클래스
    """

    def calculate_novelty(self, is_new: bool) -> float:
        """
        ① Novelty 계산:
        DB에 등록되지 않은 '처음 보는 물체'일 경우 최대 점수 0.40점 부여,
        기존에 관찰되었던 물체라면 0점 부여.
        """
        return weights.MAX_NOVELTY_SCORE if is_new else 0.0

    def calculate_visit(self, visit_count: int) -> float:
        """
        ② Visit Count 점수 계산:
        방문 횟수(visit_count)가 증가할수록 점수가 감쇄함.
        수식: max(0, 1 - visit_count / 10) * 0.20
        - visit=0  -> 0.20점
        - visit=5  -> 0.10점
        - visit>=10 -> 0.00점
        """
        factor = max(0.0, 1.0 - (visit_count / 10.0))
        return factor * weights.MAX_VISIT_SCORE

    def calculate_change(self, candidate: ObjectCandidate, memory: MemoryInfo) -> float:
        """
        ③ Change Score 계산 (차분 비교 핵심 로직):
        신규 객체(is_new=True)는 이미 Novelty 점수를 받았으므로 Change점수는 0.
        기존 객체라면 5가지 속성(색상2개, 재질, 형상, 상태)의 변경 개수(changed_fields)를 카운트하여 점수 매김.
        - 0개 변경: 0.00점
        - 1개 변경: 0.05점
        - 2개 변경: 0.10점
        - 3개 이상 변경: 0.20점
        """
        if memory.is_new:
            return 0.0

        changed_fields = 0
        if candidate.primary_color != memory.primary_color:
            changed_fields += 1
        if candidate.secondary_color != memory.secondary_color:
            changed_fields += 1
        if candidate.material != memory.material:
            changed_fields += 1
        if candidate.shape != memory.shape:
            changed_fields += 1
        if candidate.condition != memory.condition:
            changed_fields += 1

        # 변경된 속성 개수에 따른 단계별 점수 부여
        if changed_fields == 0:
            return 0.0
        elif changed_fields == 1:
            return 0.05
        elif changed_fields == 2:
            return 0.10
        else:  # 3개 이상
            return weights.MAX_CHANGE_SCORE

    def calculate_uncertainty(self, confidence: float) -> float:
        """
        ④ Uncertainty 계산:
        비전 AI의 인식 신뢰도(confidence)가 낮을수록 불확실성이 높다고 판단.
        수식: (1.0 - confidence) * 0.20
        """
        return (1.0 - confidence) * weights.MAX_UNCERTAINTY_SCORE

    def calculate_score(self, candidate: ObjectCandidate, memory: MemoryInfo) -> dict:
        """
        [최종 종합 점수 계산 함수]
        4가지 항목의 점수를 합산하고 0.0 ~ 1.0 사이로 최종 결과 클리핑
        """
        novelty = self.calculate_novelty(memory.is_new)
        visit = self.calculate_visit(memory.visit_count)
        change = self.calculate_change(candidate, memory)
        uncertainty = self.calculate_uncertainty(candidate.confidence)

        # 4개 지표 총합산 (최대 1.0)
        total_score = novelty + visit + change + uncertainty
        clamped_score = min(max(total_score, 0.0), 1.0)

        # 각 항목별 점수 및 최종 점수를 반올림하여 반환
        return {
            "novelty": round(novelty, 2),
            "visit": round(visit, 2),
            "change": round(change, 2),
            "uncertainty": round(uncertainty, 2),
            "score": round(clamped_score, 2)
        }