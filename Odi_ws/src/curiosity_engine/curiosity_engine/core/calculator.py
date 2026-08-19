from . import weights as W


# ============================================================
# 1. 단어 정돈하기 (글자 모양 맞춰주기)
# ============================================================
# AI가 물건을 보고 "Red", "red ", "RED"처럼 제각각으로 말하면
# 컴퓨터는 다 다른 말인 줄 알고 헷갈려 합니다.
# 비어있거나 뜻이 없는 단어들('-'나 'unknown' 같은 것들)을 모아둡니다.
_NULL_TOKENS = ('', 'none', 'null', 'unknown', 'n/a', 'na', '-')


def normalize(value):
    """
    글자를 깔끔하게 정리하는 장치입니다.
    대문자는 소문자로 바꾸고, 쓸데없는 공백을 지웁니다.
    비어있는 값이면 "없음(None)"으로 통일합니다.
    """
    if value is None:
        return None
    
    # 양쪽 공백을 깎아내고 모두 소문자로 바꿉니다. (예: " Red " -> "red")
    text = str(value).strip().lower()
    
    # 아무 의미 없는 단어라면 없음(None)으로 정돈합니다.
    if text in _NULL_TOKENS:
        return None
    return text


class CuriosityCalculator:
    """
    [로봇의 호기심 점수 계산기]

    로봇은 다음 두 가지 경우에 호기심을 느낍니다.
    1. "완전히 처음 보는 물건이다!" (새로움, Novelty)
    2. "내가 알던 장난감인데 색깔이나 상태가 바뀌었다!" (변화, Change)

    그리고 자주 본 물건은 점차 질리게 됩니다. (익숙함 감쇠, Decay)
    """

    # ============================================================
    # 1. 유사도 비교 — 지금 본 물건 vs 장난감 상자(DB) 속 물건
    # ============================================================

    def compare(self, candidate, record):
        """
        지금 본 물건(candidate)과 예전에 본 기록(record)의 특징을 하나씩 비교합니다.
        
        [규칙] 한쪽이라도 정보가 없으면 비교하지 않고 넘어갑니다.
        확실하게 같다는 증거가 있을 때만 점수를 줍니다.

        반환값: (닮은 비율, 같은 특징 목록, 다른 특징 목록)
        """
        score = 0.0          # 맞춘 점수
        total_weight = 0.0  # 비교할 수 있었던 총 중요도 합계
        matched = []        # 서로 같았던 특징들
        mismatched = []     # 서로 달랐던 특징들

        # 색상, 모양, 재질 등 각 특징별로 순서대로 비교합니다.
        for attr, weight in W.SIM_WEIGHTS.items():
            a = normalize(getattr(candidate, attr, None))
            b = normalize(getattr(record, attr, None))

            # 어느 한쪽이라도 정보가 비어있다면 정확히 비교할 수 없으므로 넘어갑니다.
            if a is None or b is None:
                continue

            # 정상적으로 비교할 수 있는 특징들의 중요도를 더합니다.
            total_weight += weight
            
            # 두 특징이 똑같다면 점수를 얻습니다.
            if a == b:
                score += weight
                matched.append(attr)
            else:
                mismatched.append(attr)

        # 비교 가능했던 특징들을 기준으로 점수의 비율(0.0 ~ 1.0)을 만듭니다.
        if total_weight > 0.0:
            score = score / total_weight
        else:
            score = 0.0
            
        # [안전장치] 이름 자체가 다르면 절대로 같은 물건일 수 없습니다.
        # 모양이나 색이 비슷하다고 해서 '인형'과 '컵'을 같은 물건으로 착각하지 않게 상한선(Cap)을 둡니다.
        if normalize(getattr(candidate, 'object_name', None)) != \
           normalize(getattr(record, 'object_name', None)):
            score = min(score, W.NAME_MISMATCH_CAP)

        return score, matched, mismatched

    def calculate_similarity(self, candidate, record):
        """유사도 점수 숫자만 딱 필요할 때 쓰는 줄임표 함수입니다."""
        similarity, _, _ = self.compare(candidate, record)
        return similarity

    # ============================================================
    # 2. 새로움(Novelty) — 얼마나 처음 보는 물건인가?
    # ============================================================

    def calculate_novelty(self, memory):
        """
        기억 속 물건과 얼마나 '달리 생겼는지' 거리(distance)로 참신함을 측정합니다.
        닮은 정도(similarity)가 0.8이면, 다른 정도는 0.2가 됩니다.
        """
        # 점수가 0에서 1 사이를 벗어나지 않도록 안전하게 정돈합니다.
        similarity = min(max(float(memory.similarity), 0.0), 1.0)
        distance = 1.0 - similarity  # 닮지 않은 정도 (거리가 멀수록 처음 보는 것)

        # 아예 한 번도 본 적 없는 신규 개체(is_new)라면 기본 점수(BASE)를 보장해 줍니다.
        if memory.is_new:
            return W.NOVELTY_BASE + (1.0 - W.NOVELTY_BASE) * distance

        return distance

    # ============================================================
    # 3. 변화(Change) — 내가 알던 물건이 어떻게 달라졌는가?
    # ============================================================

    def calculate_change(self, candidate, memory):
        """
        원래 알던 장난감인데 칠이 벗겨졌거나 찌그러졌는지 확인합니다.
        이름이나 재질 같은 원래 속성은 빼고, '색상'이나 '상태' 같은 겉모습 변화만 살핍니다.
        """
        # 처음 보는 물건이라면 '변화'라는 개념 자체가 성립하지 않습니다.
        if memory.is_new:
            return 0.0, []

        total_weight = 0.0
        changed_weight = 0.0
        changed_attrs = []

        # 상태 관련 특징들만 하나씩 꺼내어 비교합니다.
        for attr, weight in W.CHANGE_WEIGHTS.items():
            a = normalize(getattr(candidate, attr, None))
            b = normalize(getattr(memory, attr, None))

            # 정보가 비어있다면 변했는지 알 수 없으므로 계산에서 뺍니다.
            if a is None or b is None:
                continue

            total_weight += weight
            # 값이 서로 다르면 '변했다'고 기록합니다.
            if a != b:
                changed_weight += weight
                changed_attrs.append(attr)

        # 변한 게 없다면 변화 점수는 0점입니다.
        if total_weight <= 0.0 or changed_weight <= 0.0:
            return 0.0, []

        # 전체 상태 대비 얼마나 변했는지 비율을 구합니다.
        ratio = changed_weight / total_weight

        # 조금이라도 변했다면 그 사실 자체가 신기하므로 기본 점수(BASE)를 깔아줍니다.
        change_raw = W.CHANGE_BASE + (1.0 - W.CHANGE_BASE) * ratio

        return change_raw, changed_attrs

    # ============================================================
    # 4. 최종 호기심 점수(Curiosity Score) 합치기
    # ============================================================

    def calculate_score(self, candidate, memory):
        """
        새로움 점수와 변화 점수를 종합하여 로봇의 최종 호기심 점수를 만듭니다.
        """
        novelty_raw = self.calculate_novelty(memory)
        change_raw, changed_attrs = self.calculate_change(candidate, memory)

        # [실증 감쇠] 여러 번 본 물건은 질립니다. (자주 볼수록 decay 값이 줄어듬)
        # 단, '새로움'에만 적용하고 '변화'에는 적용하지 않습니다.
        # 자주 본 장난감이라도 갑자기 색이 바뀌면 다시 신기해해야 하기 때문입니다.
        decay = 1.0 / (1.0 + W.VISIT_DECAY * float(memory.visit_count))

        novelty_term = W.W_NOVELTY * novelty_raw * decay
        change_term = W.W_CHANGE * change_raw

        # [noisy-OR 확률 결합]
        # 단순히 평균을 내면 "처음 본 신기함(100점)" + "변화 없음(0점)"일 때 50점으로 반토막 납니다.
        # 둘 중 하나만 확실하게 터져도 호기심을 높게 유지하기 위해
        # "두 사건 모두 안 신기할 확률을 1에서 빼는 수식"을 사용합니다.
        score = 1.0 - (1.0 - novelty_term) * (1.0 - change_term)

        # 어떤 부분이 같고 다른지 최종 정리를 합니다.
        _, matched, mismatched = self.compare(candidate, memory)

        # 결과표를 만들어 돌려줍니다.
        return {
            'novelty': round(novelty_raw, 2),
            'change': round(change_raw, 2),
            'novelty_term': round(novelty_term, 2),
            'change_term': round(change_term, 2),
            'decay': round(decay, 2),
            'score': round(score, 2),
            'changed_features': changed_attrs,      # 변한 부분들
            'novel_features': mismatched,           # 새로 발견하거나 다른 부분들
            'duplicated_features': matched,         # 예전과 똑같은 부분들
        }