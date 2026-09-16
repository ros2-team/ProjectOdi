
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from odi_interfaces.msg import CuriosityDecision
from odi_interfaces.msg import DetectedObject
from odi_interfaces.msg import EncounterResult
from odi_interfaces.msg import ObservationResult

class ObjectProcessStage(str, Enum):
    NONE = "NONE"
    DETECTED = "DETECTED"

    ENCOUNTERING = "ENCOUNTERING"
    ENCOUNTER_COMPLETED = "ENCOUNTER_COMPLETED"

    EVALUATING_CURIOSITY = "EVALUATING_CURIOSITY"
    CURIOSITY_EVALUATED = "CURIOSITY_EVALUATED"

    OBSERVING = "OBSERVING"
    OBSERVATION_COMPLETED = "OBSERVATION_COMPLETED"

    IGNORED = "IGNORED"
    FINISHED = "FINISHED"
    FAILED = "FAILED"

@dataclass
class OdiBlackboard:

    # Mission status
    mission_state: str = "IDLE"
    session_id: str = ""

    # System status
    emergency: bool = False
    battery_low: bool = False
    system_ready : bool = False

    # Motivation status
    motivation: int = 80
    observation_count: int = 0
    minimum_observation_count: int = 3

    # Exploring status
    exploration_active: bool = False
    exploration_paused: bool = False
    exploration_completed: bool = False
    exploration_finished_requested: bool = False
    exploration_maximum_time: float = 300.0
    exploration_started_at: float | None = None

    detection_locked: bool = False
    handled_detection_ids: set[str] = field(default_factory=set)

    pending_objects: list[DetectedObject] = field(
        default_factory = list
    )

    current_object: Optional[DetectedObject] = None
    current_stage: ObjectProcessStage = ObjectProcessStage.NONE

    encounter_result: Optional[EncounterResult] = None
    curiosity_decision: Optional[CuriosityDecision] = None
    observation_result: Optional[ObservationResult] = None

    return_requested: bool = False
    return_completed: bool = False

    reflection_active: bool = False
    reflection_completed: bool = False

    def reset(self) -> None:
        self.session_id = ""

        self.emergency = False
        self.battery_low = False
        self.system_ready = False

        self.motivation = 80
        self.observation_count = 0
        self.minimum_observation_count = 3

        self.exploration_active = False
        self.exploration_paused = False
        self.exploration_completed = False
        self.exploration_finished_requested = False
        self.exploration_maximum_time = 300.0
        self.exploration_started_at = None

        self.detection_locked = False
        self.handled_detection_ids.clear()
        self.pending_objects.clear()

        self.current_object = None
        self.current_stage = ObjectProcessStage.NONE

        self.encounter_result = None
        self.curiosity_decision = None
        self.observation_result = None

        self.return_requested = False
        self.return_completed = False

        self.reflection_active = False
        self.reflection_completed = False





