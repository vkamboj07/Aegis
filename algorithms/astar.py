import heapq
import time
from itertools import count

from algorithms.bfs import rebuild


def search(graph, start, goal):
    """A*: UCS guided by straight-line distance to the goal."""
    t0 = time.perf_counter()
    tie = count()
    frontier = [(graph.heuristic(start, goal), next(tie), 0.0, start)]
    parent = {start: None}
    best = {start: 0.0}
    done = set()
    expanded = 0
    while frontier:
        _, _, g, node = heapq.heappop(frontier)
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
                heapq.heappush(
                    frontier, (ng + graph.heuristic(nbr, goal), next(tie), ng, nbr))
    return [], float("inf"), expanded, time.perf_counter() - t0
