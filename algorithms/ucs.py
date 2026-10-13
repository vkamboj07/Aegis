import heapq
import time
from itertools import count

from algorithms.bfs import rebuild


def search(graph, start, goal):
    """Uniform-cost search: optimal distance, no heuristic guidance."""
    t0 = time.perf_counter()
    tie = count()
    frontier = [(0.0, next(tie), start)]
    parent = {start: None}
    best = {start: 0.0}
    done = set()
    expanded = 0
    while frontier:
        g, _, node = heapq.heappop(frontier)
        if node in done:
            continue
        done.add(node)
        expanded += 1
        if node == goal:
            return rebuild(parent, goal), g, expanded, time.perf_counter() - t0
        for nbr, w in graph.neighbors(node):
            ng = g + w
            if ng < best.get(nbr, float("inf")):
                best[nbr] = ng
                parent[nbr] = node
                heapq.heappush(frontier, (ng, next(tie), nbr))
    return [], float("inf"), expanded, time.perf_counter() - t0
