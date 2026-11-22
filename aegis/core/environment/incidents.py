from dataclasses import dataclass, field
from itertools import count

_ids = count(1)


@dataclass
class Incident:
    type: str
    location: str
    severity: int = 3
    people_affected: int = 10
    time_reported: float = 0.0      # simulation hours
    status: str = "active"          # active (unassigned) | assigned | resolved
    id: int = 0
    assigned_to: str = ""           # name of the responding vehicle
    time_resolved: float = 0.0
    escalated_at: float = -1.0      # hours; last time severity was raised (default: reported)
    fired: set = field(default_factory=set)     # names of rules already applied

    def __post_init__(self):
        if not self.id:
            self.id = next(_ids)
        if self.escalated_at < 0:
            self.escalated_at = self.time_reported
