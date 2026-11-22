"""Time-ordered queue of dynamic events (road closures, new incidents)."""
import heapq
import json
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

DEFAULT_SCENARIOS = Path(__file__).resolve().parent.parent / "data" / "scenarios.json"


@dataclass(order=True)
class Event:
    time: float                     # simulation hours
    seq: int                        # keeps same-time events in insertion order
    kind: str = field(compare=False)    # new_incident | road_closure | road_reopen
    data: dict = field(default_factory=dict, compare=False)


class EventQueue:
    def __init__(self):
        self._heap = []
        self._seq = count()

    def __len__(self):
        return len(self._heap)

    def schedule(self, time, kind, **data):
        heapq.heappush(self._heap, Event(time, next(self._seq), kind, data))

    def pop_due(self, now):
        due = []
        while self._heap and self._heap[0].time <= now:
            due.append(heapq.heappop(self._heap))
        return due

    def load_events(self, events, offset=0.0):
        """Schedule scenario-format event dicts, `offset` hours from now."""
        for e in events:
            data = {k: v for k, v in e.items() if k not in ("time", "type")}
            self.schedule(offset + e["time"], e["type"], **data)

    def load_scenario(self, name, path=DEFAULT_SCENARIOS, offset=0.0):
        """Schedule every event of a named scenario, `offset` hours from now."""
        scenario = json.loads(Path(path).read_text())[name]
        self.load_events(scenario["events"], offset)
        return scenario
