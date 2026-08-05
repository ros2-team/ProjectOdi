
from dataclasses import dataclass
from typing import Optional

from odi_interfaces.msg import CuriosityDecision
from odi_interfaces.msg import ObjectCandidate

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

    # Curiosity
    current_candidate: Optional[ObjectCandidate] = None
    curiosity_decision: Optional[CuriosityDecision] = None

    # Observation
    Observation_active: bool = False
    Observation_completed: bool = False
    Observation_failed: bool = False

    # Returning
    return_requested: bool = False
    return_completed: bool = False

    # Reflection
    reflection_active: bool = False
    reflection_completed: bool = False

    def reset_runtime_state(self) -> None:
        self.emergency = False
        self.battery_low = False
        self.system_ready = False

        self.exploration_active = False
        self.exploration_completed = False
        self.exploration_paused = False

        self.current_candidate = None
        self.curiosity_decision = None

        self.Observation_active = False
        self.Observation_completed = False
        self.Observation_failed = False

        self.return_requested = False
        self.return_completed = False

        self.reflection_active = False
        self.reflection_completed = False

    def clear_candidate(self) -> None:
        self.current_candidate = None
        self.curiosity_decision = None





