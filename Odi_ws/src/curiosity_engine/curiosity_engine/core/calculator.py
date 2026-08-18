from . import weights as W


# ============================================================
# 문자열 정규화 유틸
# ============================================================
# VLM이 돌려주는 값은 "Red" / "red " / "RED" 처럼 표기가 흔들린다.
# 정규화 없이 == 로 비교하면 같은 물건을 매번 신규로 판정하게 된다.

_NULL_TOKENS = ('', 'none', 'null', 'unknown', 'n/a', 'na', '-')


def normalize(value):
    """비교용 정규화. 값이 없으면 None을 반환한다."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _NULL_TOKENS:
        return None
    return text


class CuriosityCalculator:
    """
    호기심 점수 및 객체 유사도 계산 담당.

    최종 수식
        novelty_raw = is_new ? BASE + (1-BASE)*(1-sim) : (1 - sim)
        change_raw  = 변화있음 ? BASE + (1-BASE)*ratio : 0
        decay       = 1 / (1 + VISIT_DECAY * visit_count)

        N = W_NOVELTY * novelty_raw * decay
        C = W_CHANGE  * change_raw
        score = 1 - (1-N)*(1-C)          # noisy-OR (합집합)

    가중합이 아니라 noisy-OR인 이유:
        "처음 봐서 궁금하다" 와 "알던 게 변해서 궁금하다" 는
        둘 중 하나만 성립해도 충분히 궁금한 사건이다.
        평균을 내면 한쪽이 0일 때 점수가 반토막 난다.
    """

    # ============================================================
    # 1. Similarity — 현재 객체 vs DB 기록
    # ============================================================

    def compare(self, candidate, record):
        """
        모든 속성을 비교해서 유사도와 일치/불일치 목록을 함께 돌려준다.

        NULL 처리 방침: 불일치로 센다.
            유사도는 "증거가 있어야 같다고 인정"하는 값이므로,
            정보가 비어 있는 것을 같다고 봐주면
            빈 행이 아무 객체와나 높은 유사도를 갖게 된다.

        반환: (similarity, matched, mismatched)
        """
        score = 0.0
        total_weight = 0.0      # 실제로 비교 가능했던 가중치 합
        matched = []
        mismatched = []

        for attr, weight in W.SIM_WEIGHTS.items():
            a = normalize(getattr(candidate, attr, None))
            b = normalize(getattr(record, attr, None))

            # 한쪽이라도 비어 있으면 비교 불가 → 분모에서 제외
            if a is None or b is None:
                continue

            total_weight += weight
            if a == b:
                score += weight
                matched.append(attr)
            else:
                mismatched.append(attr)

        # 비교 가능했던 속성만으로 비율을 다시 맞춘다
        if total_weight > 0.0:
            score = score / total_weight
        else:
            score = 0.0
            
        # 이름이 다르면 같은 개체일 수 없다.
        # 색/재질/형태만으로 유사도가 부풀지 않도록 상한을 건다.
        if normalize(getattr(candidate, 'object_name', None)) != \
           normalize(getattr(record, 'object_name', None)):
            score = min(score, W.NAME_MISMATCH_CAP)

        return score, matched, mismatched

    def calculate_similarity(self, candidate, record):
        """유사도 값만 필요할 때 쓰는 축약형."""
        similarity, _, _ = self.compare(candidate, record)
        return similarity

    # ============================================================
    # 2. Novelty(참신성) — 얼마나 처음 보는가
    # ============================================================

    def calculate_novelty(self, memory):
        """
        방문 횟수가 아니라 '가장 닮은 기억과의 거리'로 잰다.

        기존 방식(1/(1+visit_count))은 0회→1.0, 1회→0.5 로 뚝 떨어지는
        계단 함수여서 해상도가 없었다. similarity는 이미 계산해둔
        연속값이므로 이쪽이 훨씬 정확하다.

        is_new인 경우 BASE를 더하는 이유:
            임계값 아래로 떨어져 '신규'로 판정됐다는 사실 자체가
            이미 정보다. sim=0.75로 아슬아슬하게 신규여도
            그건 처음 보는 물건이므로 최소한의 점수는 보장한다.
        """
        similarity = min(max(float(memory.similarity), 0.0), 1.0)
        distance = 1.0 - similarity

        if memory.is_new:
            return W.NOVELTY_BASE + (1.0 - W.NOVELTY_BASE) * distance

        return distance

    # ============================================================
    # 3. Change — 알던 것이 얼마나 달라졌는가
    # ============================================================

    def calculate_change(self, candidate, memory):
        """
        memory는 '같은 개체의 가장 최근 기록'이어야 한다.
        (예전처럼 '가장 닮은 행'과 비교하면, 닮은 것으로 골랐으므로
         차이가 최소가 되도록 이미 선택된 셈이라 change가 안 터진다.)

        상태 속성(색/상태)만 비교한다. 정체성 속성(이름/재질/형태)은
        같은 개체로 묶인 이상 어차피 동일하다.

        NULL 처리 방침: 비교 대상에서 제외하고 분모를 다시 맞춘다.
            similarity와 정반대인데, 변화는 "증거가 없으면
            변했다고 단정할 수 없다"가 맞기 때문이다.
            한쪽이 비었는데 변했다고 치면 유령 변화가 계속 생긴다.

        반환: (change_raw, changed_attrs)
        """
        if memory.is_new:
            return 0.0, []

        total_weight = 0.0
        changed_weight = 0.0
        changed_attrs = []

        for attr, weight in W.CHANGE_WEIGHTS.items():
            a = normalize(getattr(candidate, attr, None))
            b = normalize(getattr(memory, attr, None))

            if a is None or b is None:
                continue  # 비교 불가 → 제외

            total_weight += weight
            if a != b:
                changed_weight += weight
                changed_attrs.append(attr)

        if total_weight <= 0.0 or changed_weight <= 0.0:
            return 0.0, []

        ratio = changed_weight / total_weight

        # base + 비율: '변했다는 사실 자체'에 최소 점수를 보장한다.
        # condition 하나만 바뀐 것도 충분히 궁금한 사건이기 때문.
        change_raw = W.CHANGE_BASE + (1.0 - W.CHANGE_BASE) * ratio

        return change_raw, changed_attrs

    # ============================================================
    # 4. 최종 Curiosity Score
    # ============================================================

    def calculate_score(self, candidate, memory):
        novelty_raw = self.calculate_novelty(memory)
        change_raw, changed_attrs = self.calculate_change(candidate, memory)

        # 익숙함 감쇠 — novelty에만 적용한다.
        # change에 곱하면 자주 본 물건의 변화를 놓치게 된다.
        decay = 1.0 / (1.0 + W.VISIT_DECAY * float(memory.visit_count))

        novelty_term = W.W_NOVELTY * novelty_raw * decay
        change_term = W.W_CHANGE * change_raw

        # noisy-OR: 두 항 모두 흥미롭지 않을 확률의 여집합.
        # 각 항이 독립적으로 점수를 끝까지 밀어올릴 수 있고,
        # 구조상 절대 1.0을 넘지 않으므로 clamp가 필요 없다.
        score = 1.0 - (1.0 - novelty_term) * (1.0 - change_term)

        # 이번 관측에서 처음 보는 특징 / 이미 익숙한 특징
        _, matched, mismatched = self.compare(candidate, memory)

        return {
            'novelty': round(novelty_raw, 2),
            'change': round(change_raw, 2),
            'novelty_term': round(novelty_term, 2),
            'change_term': round(change_term, 2),
            'decay': round(decay, 2),
            'score': round(score, 2),
            'changed_features': changed_attrs,
            'novel_features': mismatched,
            'duplicated_features': matched,
        }