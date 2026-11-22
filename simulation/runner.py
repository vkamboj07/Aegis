"""Headless runs: scripted scenarios and the all-pairs algorithm benchmark."""
import itertools
import json

from algorithms import ALGORITHMS
from environment.city import CityGraph
from environment.events import DEFAULT_SCENARIOS
from simulation.engine import Simulation


def scenario_names(path=DEFAULT_SCENARIOS):
    return list(json.loads(path.read_text()))


def run_scenario(name, dt=0.02, max_hours=72.0):
    """Run one named scenario until every event fired and every incident is
    resolved (or max_hours passes). Uses a fresh graph: closures mutate it."""
    sim = Simulation(CityGraph.load())
    sim.queue.load_scenario(name)
    while sim.now < max_hours:
        sim.step(dt)
        if not sim.queue and not sim.open_incidents():
            break
    return sim


def run_all(names=None):
    return {n: run_scenario(n) for n in (names or scenario_names())}


def scenario_rows(sims):
    """Flatten {scenario: Simulation} into tagged record dicts."""
    return [{**r, "scenario": name} for name, sim in sims.items() for r in sim.records]


def benchmark(graph=None):
    """Every algorithm on every ordered pair of distinct cities."""
    graph = graph or CityGraph.load()
    rows = []
    for start, goal in itertools.permutations(graph.nodes, 2):
        for name, search in ALGORITHMS.items():
            path, cost, expanded, elapsed = search(graph, start, goal)
            rows.append({"algorithm": name, "start": start, "goal": goal,
                         "distance_km": round(cost, 1), "nodes_expanded": expanded,
                         "search_ms": round(elapsed * 1000, 4)})
    return rows
