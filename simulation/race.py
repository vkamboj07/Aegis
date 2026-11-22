"""Route race: the route a vehicle drives, plus a ghost for every other
algorithm's route to the same place, moving at the same speed."""
from dataclasses import dataclass, field


@dataclass
class Ghost:
    algorithm: str
    path: list
    cost: float
    km: float = 0.0
    arrived_at: float = None        # sim hour


@dataclass
class Race:
    vehicle: str
    incident: int
    start: float
    chosen: str
    options: dict                   # algorithm -> (path, cost, nodes expanded, seconds)
    ghosts: list = field(default_factory=list)
    arrived_at: float = None        # when the real vehicle arrived
    ended: bool = False             # superseded by a replan, or the vehicle broke down

    @classmethod
    def begin(cls, vehicle, incident, now, chosen, options, progress=0.0):
        ghosts = [Ghost(a, r[0], r[1], km=progress)
                  for a, r in options.items() if a != chosen and r[0]]
        return cls(vehicle, incident, now, chosen, options, ghosts)

    @property
    def destination(self):
        return self.options[self.chosen][0][-1]

    @property
    def running(self):
        return not self.ended and (self.arrived_at is None
                                   or any(g.arrived_at is None for g in self.ghosts))

    def advance(self, km, now):
        if self.ended:
            return
        for g in self.ghosts:
            if g.arrived_at is None:
                g.km = min(g.cost, g.km + km)
                if g.km >= g.cost:
                    g.arrived_at = now
