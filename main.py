"""AEGIS entry point.

  python main.py                        launch the Pygame map
  python main.py --compare Delhi Jaipur print algorithm comparison for one incident
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from algorithms import ALGORITHMS
from environment.city import CityGraph

AVG_SPEED_KMH = 60


def compare(graph, start, goal):
    print(f"{start} -> {goal}")
    print(f"{'Algo':<5}{'Dist km':>9}{'Time h':>8}{'Expanded':>10}  Route")
    for name, search in ALGORITHMS.items():
        path, cost, expanded, _ = search(graph, start, goal)
        print(f"{name:<5}{cost:>9.0f}{cost / AVG_SPEED_KMH:>8.1f}{expanded:>10}  "
              + " -> ".join(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs=2, metavar=("START", "GOAL"))
    args = ap.parse_args()
    graph = CityGraph.load()
    if args.compare:
        compare(graph, *args.compare)
    else:
        from visualization.pygame_ui import App
        App(graph).run()


if __name__ == "__main__":
    main()
