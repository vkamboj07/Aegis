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


def analyze():
    """Run the benchmark and every scenario headlessly; write CSVs and charts."""
    from simulation.recorder import (BENCH_FIELDS, RESULTS_DIR, SIM_FIELDS, load_csv,
                                     save_csv)
    from simulation.runner import benchmark, run_all, scenario_rows
    from visualization.charts import make_all

    save_csv(benchmark(), RESULTS_DIR / "algorithm_benchmark.csv", BENCH_FIELDS)
    sims = run_all()
    save_csv(scenario_rows(sims), RESULTS_DIR / "simulation_results.csv", SIM_FIELDS)
    for name, sim in sims.items():
        done = sum(i.status == "resolved" for i in sim.incidents)
        print(f"{name:<16}{done}/{len(sim.incidents)} resolved in {sim.now:.1f} h")
    charts = make_all(load_csv(RESULTS_DIR / "algorithm_benchmark.csv"),
                      load_csv(RESULTS_DIR / "simulation_results.csv"), RESULTS_DIR)
    print("wrote", RESULTS_DIR / "algorithm_benchmark.csv")
    print("wrote", RESULTS_DIR / "simulation_results.csv")
    for c in charts:
        print("wrote", c)


def interpret(graph, text, use_llm):
    """Show how the prompt engine reads a scenario, as structured JSON."""
    import json
    from prompt_engine.parser import describe
    from prompt_engine.scenario_generator import build_scenario
    scenario = build_scenario(text, graph, use_llm=use_llm)
    print(json.dumps({"description": scenario["description"], "events": scenario["events"]}, indent=2))
    for event in scenario["events"]:
        print("  ", describe(event))
    for warning in scenario["warnings"]:
        print("warning:", warning)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs=2, metavar=("START", "GOAL"))
    ap.add_argument("--analyze", action="store_true",
                    help="run all scenarios + benchmark, write results/*.csv and charts")
    ap.add_argument("--parse", metavar="TEXT",
                    help="interpret a natural-language scenario and print the structured events")
    ap.add_argument("--llm", action="store_true",
                    help="allow the optional LLM fallback when the keyword parser finds nothing")
    args = ap.parse_args()
    if args.analyze:
        return analyze()
    graph = CityGraph.load()
    if args.parse:
        interpret(graph, args.parse, args.llm)
    elif args.compare:
        compare(graph, *args.compare)
    else:
        from visualization.pygame_ui import App
        App(graph, use_llm=args.llm).run()


if __name__ == "__main__":
    main()
