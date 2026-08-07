class ObjectCandidate:
    """
    현재 인지된 객체 정보.
    Perception → Curiosity Engine으로 전달되는
    실시간 객체 데이터.
    """

    def __init__(
        self,
        object_name: str,
        primary_color: str,
        secondary_color: str,
        material: str,
        shape: str,
        condition: str
    ):

        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition


class MemoryInfo:
    """
    과거에 관찰했던 객체의 기억 정보.
    현재는 임시 Memory DB에서 사용하고,
    추후 World Memory Node / 실제 DB와 연결한다.
    """

    def __init__(
        self,
        visit_count: int = 0,
        is_new: bool = True,
        primary_color: str = "",
        secondary_color: str = "",
        material: str = "",
        shape: str = "",
        condition: str = ""
    ):

        self.visit_count = visit_count
        self.is_new = is_new
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition