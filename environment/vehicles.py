from dataclasses import dataclass, field

# kind: (incident types it can serve, body colour)
KINDS = {
    "Fire Truck": (("Fire",), (205, 45, 45)),
    "Ambulance": (("Medical", "Accident"), (248, 248, 248)),
    "Police": (("Accident",), (45, 95, 205)),
}
FLEET = [("Fire Truck", 2), ("Ambulance", 2), ("Police", 1)]


@dataclass
class Vehicle:
    name: str
    kind: str
    location: str                   # last junction passed, or where it is parked
    status: str = "idle"            # idle | dispatched | on_scene | returning | broken
    algorithm: str = ""             # search algorithm whose route it is driving
    path: list = field(default_factory=list)
    cost: float = 0.0
    nodes_expanded: int = 0
    search_time: float = 0.0
    seg: int = 0
    seg_progress: float = 0.0       # km travelled along the current segment
    moving: bool = False
    incident: int = 0               # incident being served, 0 = none
    target: str = ""                # destination of the current trip
    pending: tuple = None           # (best, options) to switch to at the next junction
    backtrack: bool = False         # driving back to the last junction before switching
    replans: int = 0
    until: float = 0.0              # sim hour when on-scene work or a repair ends

    @property
    def handles(self):
        return KINDS[self.kind][0]

    @property
    def color(self):
        return KINDS[self.kind][1]

    @property
    def free(self):
        """Available for a new job (a returning vehicle can be re-tasked)."""
        return self.status in ("idle", "returning")

    def can_serve(self, incident_type):
        return incident_type in self.handles

    def set_route(self, best, options, progress=0.0):
        """Drive options[best], a route that starts at the vehicle's current node."""
        path, cost, expanded, elapsed = options[best]
        self.algorithm, self.path, self.cost = best, path, cost
        self.nodes_expanded, self.search_time = expanded, elapsed
        self.seg, self.seg_progress = 0, progress
        self.moving = len(path) > 1


def default_fleet(depot):
    """Every vehicle starts parked at the one depot."""
    return [Vehicle(f"{kind} {i}", kind, depot) for kind, n in FLEET for i in range(1, n + 1)]
