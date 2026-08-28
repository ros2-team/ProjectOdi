from . import weights as W


# ============================================================
# 값 정규화 유틸
# ============================================================
# AI가 돌려주는 값은 "Red" / "red " / "NORMAL" 처럼 표기가 흔들린다.
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


def normalize_features(values):
    """
    특징 리스트(object_special_features)를 집합으로 정규화한다.
    예) ["손잡이 있음", "파란 무늬"] -> {"손잡이 있음", "파란 무늬"}
    비어 있으면 None (= 비교 불가)
    """
    if not values:
        return None
    items = {
        normalize(v)
        for v in values
        if normalize(v) is not None
    }
    return items or None


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
    # 1. Similarity — 현재 객체 vs 과거 기록
    # ============================================================

    def compare(self, candidate, record):
        """
        World Memory가 object_name이 같은 기록만 돌려주므로
        여기서 이름은 비교하지 않는다. 색/재질/형태/상태/특징만 본다.

        NULL 처리 방침: 비교 대상에서 제외하고 분모를 재정규화한다.
            1차 조우는 material/condition이 비어 올 수 있고
            과거 기록은 정밀 관찰 결과라 값이 다 채워져 있다.
            빈 값을 불일치로 세면 같은 물체인데도 유사도가
            임계값을 넘지 못해 매번 신규로 판정된다.

        반환: (similarity, matched, mismatched)
        """
        score = 0.0
        total_weight = 0.0      # 실제로 비교 가능했던 가중치 합
        matched = []
        mismatched = []

        for attr, weight in W.SIM_WEIGHTS.items():
            if attr == 'special_features':
                a = normalize_features(getattr(candidate, attr, None))
                b = normalize_features(getattr(record, attr, None))
                if a is None or b is None:
                    continue
                total_weight += weight
                # 특징은 부분 일치를 인정한다 (자카드 유사도)
                overlap = len(a & b) / len(a | b)
                score += weight * overlap
                if overlap >= 0.5:
                    matched.append(attr)
                else:
                    mismatched.append(attr)
                continue

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

        return score, matched, mismatched

    def calculate_similarity(self, candidate, record):
        """유사도 값만 필요할 때 쓰는 축약형."""
        similarity, _, _ = self.compare(candidate, record)
        return similarity

    # ============================================================
    # 2. Novelty — 얼마나 처음 보는가
    # ============================================================

    def calculate_novelty(self, memory):
        """
        방문 횟수가 아니라 '가장 닮은 기억과의 거리'로 잰다.

        is_new인 경우 BASE를 더하는 이유:
            임계값 아래로 떨어져 '신규'로 판정됐다는 사실 자체가
            이미 정보다. 과거 기록이 0건이면 similarity가 0이므로
            novelty는 1.0이 된다.
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
        (World Memory 응답이 stored_at DESC 정렬이므로 배열의 0번)

        NULL 처리 방침: 비교 대상에서 제외하고 분모를 다시 맞춘다.
            similarity와 정반대인데, 변화는 "증거가 없으면
            변했다고 단정할 수 없다"가 맞기 때문이다.

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
        score = 1.0 - (1.0 - novelty_term) * (1.0 - change_term)

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