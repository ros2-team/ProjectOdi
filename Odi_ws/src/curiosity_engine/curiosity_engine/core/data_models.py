class ObjectCandidate:
    """실시간 AI 인식 데이터 객체"""
    def __init__(self, track_id: int, confidence: float, object_name: str,
                 primary_color: str, secondary_color: str, material: str,
                 shape: str, condition: str):
        self.track_id = track_id
        self.confidence = confidence
        self.object_name = object_name
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition


class MemoryInfo:
    """DB에 저장되어 있는 과거 관찰 데이터"""
    def __init__(self, visit_count: int = 0, is_new: bool = True,
                 primary_color: str = "", secondary_color: str = "",
                 material: str = "", shape: str = "", condition: str = ""):
        self.visit_count = visit_count
        self.is_new = is_new  # DB 존재 여부 (Novelty 판단 기준)
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.material = material
        self.shape = shape
        self.condition = condition