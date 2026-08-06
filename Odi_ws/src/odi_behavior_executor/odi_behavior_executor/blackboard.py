
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
    mission_state:str = "IDLE"

    # System status
    emergency: bool = False
    battery_low: bool = False
    system_ready : bool = False

    # Exploring status
    exploration_active: bool = False
    exploration_paused: bool = False
    exploration_completed: bool = False

    detection_locked: bool = False

    pending_objects: list[DetectedObject] = field(
        default_factory = list
    )

    current_object: Optional[DetectedObject] = None
    current_stage: ObjectProcessStage = ObjectProcessStage.NONE

    encounter_result: Optional[DetectedObject] = None
    curiosity_decision: Optional[CuriosityDecision] = None
    observation_result: Optional[ObservationResult] = None

    return_requested: bool = False
    return_completed: bool = False

    reflection_active: bool = False
    reflection_completed: bool = False

    def reset(self) -> None:
        self.emergency = False
        self.battery_low = False
        self.system_ready = False

        self.exploration_active = False
        self.exploration_paused = False
        self.exploration_completed = False

        self.detection_locked = False
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





