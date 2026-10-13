import json
import math
from pathlib import Path

from environment.roads import Road

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "cities.json"


def haversine(c1, c2):
    """Great-circle distance in km between two (lat, lon) pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*c1, *c2))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


class CityGraph:
    """Weighted undirected road graph. Closed roads are invisible to search."""

    def __init__(self, coords, roads):
        self.coords = dict(coords)
        self.roads = {}
        self._adj = {n: [] for n in self.coords}
        for r in roads:
            self.roads[r.key] = r
            self._adj[r.a].append(r)
            self._adj[r.b].append(r)

    @classmethod
    def load(cls, path=DEFAULT_DATA):
        data = json.loads(Path(path).read_text())
        coords = {n: (c["lat"], c["lon"]) for n, c in data["cities"].items()}
        roads = [Road(a, b, d) for a, b, d in data["roads"]]
        graph = cls(coords, roads)
        graph.validate()
        return graph

    @property
    def nodes(self):
        return list(self.coords)

    def neighbors(self, node):
        """Yield (neighbor, distance) over open roads only."""
        for r in self._adj[node]:
            if not r.closed:
                yield r.other(node), r.distance

    def road(self, a, b):
        return self.roads.get(frozenset((a, b)))

    def set_closed(self, a, b, closed=True):
        self.roads[frozenset((a, b))].closed = closed

    def heuristic(self, a, b):
        """Straight-line km; admissible because roads are never shorter."""
        return haversine(self.coords[a], self.coords[b])

    def path_cost(self, path):
        return sum(self.road(u, v).distance for u, v in zip(path, path[1:]))

    def validate(self):
        for r in self.roads.values():
            if r.distance < self.heuristic(r.a, r.b) - 1e-6:
                raise ValueError(
                    f"Road {r.a}-{r.b} ({r.distance} km) is shorter than the "
                    f"straight line; A* heuristic would be inadmissible")
