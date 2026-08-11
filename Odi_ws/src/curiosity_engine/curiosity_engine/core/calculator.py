class CuriosityCalculator:
    """
    호기심 점수 및 객체 유사도 계산 담당.

    역할
    1. Novelty 계산
    2. Change 계산
    3. DB 객체와 현재 객체의 Similarity 계산
    4. 최종 Curiosity Score 계산

    현재 SemanticLabel.msg에 confidence가 없기 때문에
    Uncertainty는 사용하지 않는다.
    """

    def __init__(self):
        pass

    # ============================================================
    # 1. Novelty 계산
    # ============================================================

    def calculate_novelty(self, memory):
        """
        처음 보는 객체일수록 Novelty가 높다.

        visit_count = 0 → 1.0
        visit_count = 1 → 0.5
        visit_count = 2 → 0.33
        visit_count = 5 → 0.16
        """

        return 1.0 / (1.0 + float(memory.visit_count))

    # ============================================================
    # 2. Change 계산
    # ============================================================

    def calculate_change(self, candidate, memory):
        """
        현재 객체와 기존 Memory의 특징을 비교한다.

        비교 대상:
        - primary_color
        - secondary_color
        - material
        - shape
        - condition

        반환값:
            0.0 ~ 1.0
        """

        # 처음 보는 객체는 비교할 과거 정보가 없다.
        if memory.is_new:
            return 0.0

        total = 5
        changed = 0

        if candidate.primary_color != memory.primary_color:
            changed += 1

        if candidate.secondary_color != memory.secondary_color:
            changed += 1

        if candidate.material != memory.material:
            changed += 1

        if candidate.shape != memory.shape:
            changed += 1

        if candidate.condition != memory.condition:
            changed += 1

        return changed / total

    # ============================================================
    # 3. 객체 Similarity 계산
    # ============================================================

    def calculate_similarity(self, candidate, db_candidate):
        """
        현재 인지 객체와 DB에 저장된 객체의
        특징별 일치도를 계산한다.

        각 특징마다 중요도가 다르기 때문에
        서로 다른 가중치를 적용한다.

        반환값:
            0.0 ~ 1.0
        """

        score = 0.0

        # 객체 종류
        if candidate.object_name == db_candidate.object_name:
            score += 0.30

        # 주요 색상
        if candidate.primary_color == db_candidate.primary_color:
            score += 0.20

        # 보조 색상
        if candidate.secondary_color == db_candidate.secondary_color:
            score += 0.10

        # 재질
        if candidate.material == db_candidate.material:
            score += 0.15

        # 형태
        if candidate.shape == db_candidate.shape:
            score += 0.15

        # 상태
        if candidate.condition == db_candidate.condition:
            score += 0.10

        return score

    # ============================================================
    # 4. 최종 Curiosity Score
    # ============================================================

    def calculate_score(self, candidate, memory):
        """
        최종 호기심 점수를 계산한다.

        구조:

            Novelty
                +
            Change
                ↓
        Curiosity Score

        현재 confidence가 없으므로
        Uncertainty는 사용하지 않는다.
        """

        # --------------------------------------------------------
        # Novelty
        # --------------------------------------------------------

        novelty = self.calculate_novelty(memory)

        # --------------------------------------------------------
        # Change
        # --------------------------------------------------------

        change = self.calculate_change(
            candidate,
            memory
        )

        # --------------------------------------------------------
        # 가중치
        # --------------------------------------------------------

        novelty_weight = 0.6
        change_weight = 0.4

        # --------------------------------------------------------
        # 최종 점수
        # --------------------------------------------------------

        score = (
            novelty * novelty_weight
            +
            change * change_weight
        )

        # 0 ~ 1 범위 제한
        score = min(
            max(score, 0.0),
            1.0
        )

        return {
            "novelty": round(novelty, 2),
            "change": round(change, 2),
            "score": round(score, 2)
        }