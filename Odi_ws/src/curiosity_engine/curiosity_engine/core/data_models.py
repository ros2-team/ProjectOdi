class ObjectCandidate:
    """
    현재 조우한 객체 정보.
    EncounterResult.label → Curiosity Engine으로 전달되는 데이터.
    """

    def __init__(
        self,
        object_name: str = '',
        primary_color: str = '',
        secondary_color: str = '',
        material: str = '',
        shape: str = '',
        condition: str = '',
        special_features=None
    ):
        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition
        self.special_features = list(special_features or [])

    def __repr__(self):
        return (
            f'ObjectCandidate({self.object_name}, '
            f'{self.primary_color}/{self.secondary_color}, '
            f'{self.material}, {self.shape}, {self.condition})'
        )


class MemoryInfo:
    """
    과거에 관찰했던 객체의 기억 정보.

    is_new=False 인 경우 색/상태 필드에는
    '같은 개체의 가장 최근 기록' 값이 들어간다.
    change 계산이 이 값을 기준으로 이뤄지기 때문이다.
    """

    def __init__(
        self,
        visit_count: int = 0,
        is_new: bool = True,
        object_name: str = '',
        primary_color: str = '',
        secondary_color: str = '',
        material: str = '',
        shape: str = '',
        condition: str = '',
        special_features=None,
        similarity: float = 0.0,
        compared_record_count: int = 0,
        memory_id: str = ''
    ):
        self.visit_count = visit_count
        self.is_new = is_new
        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition
        self.special_features = list(special_features or [])
        self.similarity = similarity
        self.compared_record_count = compared_record_count
        self.memory_id = memory_id   # World Memory의 기록 id (추적용)

    def __repr__(self):
        return (
            f'MemoryInfo(new={self.is_new}, visits={self.visit_count}, '
            f'sim={self.similarity:.2f}, memory_id={self.memory_id})'
        )