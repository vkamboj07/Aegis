from dataclasses import dataclass
from itertools import count

_ids = count(1)


@dataclass
class Incident:
    type: str
    location: str
    severity: int = 3
    people_affected: int = 10
    time_reported: float = 0.0
    status: str = "active"          # active | resolved
    id: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next(_ids)
