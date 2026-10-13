import time

from algorithms.bfs import rebuild


def search(graph, start, goal):
    """Depth-first (iterative): finds *a* path, usually not a short one."""
    t0 = time.perf_counter()
    stack = [start]
    parent = {start: None}
    expanded = 0
    while stack:
        node = stack.pop()
        expanded += 1
        if node == goal:
            path = rebuild(parent, goal)
            return path, graph.path_cost(path), expanded, time.perf_counter() - t0
        # reversed so the first-listed neighbour is explored first
        for nbr, _ in reversed(list(graph.neighbors(node))):
            if nbr not in parent:
                parent[nbr] = node
                stack.append(nbr)
    return [], float("inf"), expanded, time.perf_counter() - t0
