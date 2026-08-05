class ObjectCandidate:
    def __init__(self, track_id: int, class_name: str, confidence: float):
        self.track_id = track_id
        self.class_name = class_name
        self.confidence = confidence


class MemoryInfo:
    def __init__(self, visit_count: int, change: bool):
        self.visit_count = visit_count
        self.change = change