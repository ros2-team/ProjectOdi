class ObjectCandidate:
    """
    현재 인지된 객체 정보.
    Perception → Curiosity Engine으로 전달되는 실시간 객체 데이터.
    """

    def __init__(
        self,
        object_name: str = '',
        primary_color: str = '',
        secondary_color: str = '',
        material: str = '',
        shape: str = '',
        condition: str = ''
    ):
        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition

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

    similarity / compared_record_count 는 예전에 노드에서
    나중에 붙이는 방식이었는데, 한 경로라도 빠뜨리면
    AttributeError로 서비스가 죽으므로 생성자로 옮겼다.
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
        similarity: float = 0.0,
        compared_record_count: int = 0,
        record_id=None
    ):
        self.visit_count = visit_count
        self.is_new = is_new
        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition
        self.similarity = similarity
        self.compared_record_count = compared_record_count
        self.record_id = record_id   # 매칭된 DB 행 id (추적/디버깅용)

    def __repr__(self):
        return (
            f'MemoryInfo(new={self.is_new}, visits={self.visit_count}, '
            f'sim={self.similarity:.2f}, id={self.record_id})'
        )