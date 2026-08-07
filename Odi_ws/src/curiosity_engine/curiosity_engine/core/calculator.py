class CuriosityCalculator:
    """
    호기심 점수 계산 담당.

    현재 사용 요소:
    - Novelty : 처음 보는 물체인지
    - Visit Count : 얼마나 자주 봤는지
    - Change : 기존에 봤던 물체와 특징이 달라졌는지

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
        처음 보는 물체일수록 Novelty가 높다.

        처음 발견:
            visit_count = 0
            → novelty = 1.0

        1번 본 물체:
            visit_count = 1
            → novelty = 0.5

        2번 본 물체:
            visit_count = 2
            → novelty = 0.33

        5번 본 물체:
            visit_count = 5
            → novelty = 0.16
        """

        return 1.0 / (1.0 + float(memory.visit_count))

    # ============================================================
    # 2. Change 계산
    # ============================================================

    def calculate_change(self, candidate, memory):
        """
        현재 객체의 특징과 과거 기억을 비교한다.

        비교 대상:
        - primary_color
        - secondary_color
        - material
        - shape
        - condition

        특징이 달라졌으면 변화가 발생했다고 판단한다.

        반환값:
            0.0 ~ 1.0
        """

        # 처음 보는 객체라면
        # "변화"를 판단할 과거 정보가 없다.
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
    # 3. 최종 Curiosity Score
    # ============================================================

    def calculate_score(self, candidate, memory):
        """
        최종 호기심 점수를 계산한다.

        현재 구조:

            Novelty
                +
            Change
                ↓
        Curiosity Score

        현재는 confidence가 없으므로
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

        # 처음 보는 물체인지
        # 기존 물체의 변화인지
        #
        # 현재는 Novelty와 Change를 동일하게 반영한다.

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