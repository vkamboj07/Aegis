from dataclasses import dataclass, field


@dataclass
class Vehicle:
    name: str
    algorithm: str                  # key into algorithms.ALGORITHMS
    color: tuple
    location: str
    path: list = field(default_factory=list)
    cost: float = 0.0
    nodes_expanded: int = 0
    search_time: float = 0.0
    # animation state
    seg: int = 0
    seg_progress: float = 0.0       # km travelled along current segment
    moving: bool = False

    def dispatch(self, result):
        path, cost, expanded, elapsed = result
        self.path, self.cost = path, cost
        self.nodes_expanded, self.search_time = expanded, elapsed
        self.seg, self.seg_progress = 0, 0.0
        self.moving = len(path) > 1


def default_fleet():
    return [
        Vehicle("Ambulance",    "BFS", (230, 60, 60),  "Delhi"),
        Vehicle("Police Jeep",  "DFS", (60, 110, 230), "Gurugram"),
        Vehicle("Fire Truck",   "UCS", (240, 150, 40), "Faridabad"),
        Vehicle("Army Vehicle", "A*",  (70, 170, 90),  "Agra"),
    ]
