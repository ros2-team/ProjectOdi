from .data_models import ObjectCandidate, MemoryInfo
from . import weights  # 가중치 설정 값 임포트

class CuriosityCalculator:
    """객체 정보와 메모리 데이터를 수식에 넣어 호기심 점수를 계산하는 클래스"""

    def calculate_novelty(self, visit_count: int) -> float:
        # 방문횟수가 적을수록 높은 값을 반환(역수계싼)
        return 1.0 / (1.0 + float(visit_count))

    def calculate_uncertainty(self, confidence: float) -> float:
        # 인식 신뢰도가 낮을수롣 높은 불확실성 반환
        return 1.0 - confidence

    def calculate_score(self, candidate: ObjectCandidate, memory: MemoryInfo) -> dict:
        # Novelty, Uncertainty, Change 가중치를 조합해 최종 호기심 점수를 계산 
        
        # 1. 개별지표 계산
        novelty = self.calculate_novelty(memory.visit_count)
        uncertainty = self.calculate_uncertainty(candidate.confidence)

        # 2. 변화 여부에 따른 가중치 배율 설정
        change_weight = weights.WEIGHT_CHANGE if memory.change else 1.0
        
        # 3. 가중치 합산 및 최종 점수 산출
        raw_score = (weights.WEIGHT_NOVELTY * novelty + weights.WEIGHT_UNCERTAINTY * uncertainty) * change_weight
        
        # 4. 점수를 0.0 ~ 1.0 범위로 클리핑 (제한)
        score = min(max(raw_score, 0.0), 1.0)

        # 계산 결과 리턴
        return {
            "novelty": round(novelty, 2),
            "uncertainty": round(uncertainty, 2),
            "score": round(score, 2)
        }