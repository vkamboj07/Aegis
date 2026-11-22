"""Responsible-AI check: does the system serve every city about equally well?

For each city, one Fire incident (severity 3, 50 people) is reported into an otherwise empty
fleet stationed at base. The response time is hours from report to arrival. The result is
compared with the road distance from base, and cities far above the median are flagged.

This does not measure fairness across population groups: the data has no population figures.
It measures how much a city's location alone changes the service it gets.
"""
import statistics

from algorithms import ALGORITHMS
from environment.city import CityGraph
from simulation.engine import Simulation

FLAG_RATIO = 1.5    # a city is flagged when its response is this many times the median
MAX_HOURS = 72.0


def city_response(graph, city, kind="Fire", severity=3, people=50, dt=0.05):
    """Hours from report to arrival for one incident in `city`, or None if never served."""
    sim = Simulation(graph)
    inc = sim.report(kind, city, severity, people)
    while sim.now < MAX_HOURS and inc.status != "resolved":
        sim.step(dt)
    if inc.status != "resolved":
        return None
    return inc.time_resolved - inc.time_reported


def fairness_rows(graph=None):
    """One row per city, sorted by response time (slowest first)."""
    graph = graph or CityGraph.load()
    rows = []
    for city in graph.nodes:
        _, distance, _, _ = ALGORITHMS["A*"](graph, graph.depot, city)
        hours = city_response(graph, city)
        rows.append({"city": city, "distance_km": round(distance, 1),
                     "response_h": None if hours is None else round(hours, 3)})
    served = [r["response_h"] for r in rows if r["response_h"] is not None]
    median = statistics.median(served) if served else 0.0
    for r in rows:
        r["ratio_to_median"] = (round(r["response_h"] / median, 2)
                                if r["response_h"] is not None and median else None)
        r["flagged"] = bool(r["ratio_to_median"] and r["ratio_to_median"] >= FLAG_RATIO)
    return sorted(rows, key=lambda r: -(r["response_h"] or 0))


def summary(rows):
    """Median response, the flagged cities, and how strongly distance predicts response."""
    pairs = [(r["distance_km"], r["response_h"]) for r in rows if r["response_h"] is not None]
    served = [h for _, h in pairs]
    corr = statistics.correlation(*zip(*pairs)) if len(pairs) > 2 else float("nan")
    return {
        "cities": len(rows),
        "served": len(served),
        "median_h": round(statistics.median(served), 2) if served else None,
        "max_h": round(max(served), 2) if served else None,
        "flagged": [r["city"] for r in rows if r["flagged"]],
        "distance_response_correlation": round(corr, 3),
    }


FIELDS = ["city", "distance_km", "response_h", "ratio_to_median", "flagged"]
