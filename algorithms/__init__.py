"""Every search shares: search(graph, start, goal) -> (path, cost, nodes_expanded, time_taken)."""
from algorithms import astar, bfs, dfs, ucs

ALGORITHMS = {
    "BFS": bfs.search,
    "DFS": dfs.search,
    "UCS": ucs.search,
    "A*": astar.search,
}
