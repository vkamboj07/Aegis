import time
from collections import deque


def search(graph, start, goal):
    """Breadth-first: fewest hops, ignores road length when choosing."""
    t0 = time.perf_counter()
    frontier = deque([start])
    parent = {start: None}
    expanded = 0
    while frontier:
        node = frontier.popleft()
        expanded += 1
        if node == goal:
            path = rebuild(parent, goal)
            return path, graph.path_cost(path), expanded, time.perf_counter() - t0
        for nbr, _ in graph.neighbors(node):
            if nbr not in parent:
                parent[nbr] = node
                frontier.append(nbr)
    return [], float("inf"), expanded, time.perf_counter() - t0


def rebuild(parent, goal):
    path = []
    while goal is not None:
        path.append(goal)
        goal = parent[goal]
    return path[::-1]
