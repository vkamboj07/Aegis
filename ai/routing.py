"""Run every search algorithm on the same trip and pick the route to drive."""
from algorithms import ALGORITHMS

PREFERENCE = ["A*", "UCS", "BFS", "DFS"]    # tie-break when distance and effort are equal


def plan_routes(graph, start, goal):
    """Returns (best, options): options maps every algorithm to its
    (path, cost, nodes_expanded, seconds); best is the shortest route, then
    the one that expanded fewest nodes. Nothing is predefined per vehicle."""
    options = {name: ALGORITHMS[name](graph, start, goal) for name in PREFERENCE}
    best = min(PREFERENCE, key=lambda n: (options[n][1], options[n][2], PREFERENCE.index(n)))
    return best, options
