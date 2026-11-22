"""AEGIS entry point.

  python main.py                        launch the Pygame map
  python main.py --compare Delhi Jaipur print algorithm comparison for one incident
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aegis.core.algorithms import ALGORITHMS
from aegis.core.environment.city import CityGraph

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
    from aegis.core.simulation.recorder import (BENCH_FIELDS, RESULTS_DIR, SIM_FIELDS, load_csv,
                                     save_csv)
    from aegis.core.simulation.runner import benchmark, run_all, scenario_rows
    from aegis.charts import make_all

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


def fairness():
    """Response time per city for one standard incident, compared with distance from base."""
    from aegis.core.simulation.fairness import FIELDS, fairness_rows, summary
    from aegis.core.simulation.recorder import RESULTS_DIR, save_csv
    rows = fairness_rows()
    save_csv(rows, RESULTS_DIR / "fairness.csv", FIELDS)
    print(f"{'City':<13}{'Km':>6}{'Hours':>8}{'x median':>10}  flag")
    for r in rows:
        flag = "SLOW" if r["flagged"] else ""
        print(f"{r['city']:<13}{r['distance_km']:>6.0f}{r['response_h']:>8.2f}"
              f"{r['ratio_to_median']:>10.2f}  {flag}")
    s = summary(rows)
    print(f"median {s['median_h']} h, slowest {s['max_h']} h, "
          f"distance-response correlation {s['distance_response_correlation']}")
    print("wrote", RESULTS_DIR / "fairness.csv")


def explain_rules(graph, kind, city, people):
    """Why each knowledge rule would or would not fire for this incident (backward chaining)."""
    from aegis.core.ai.logic import explain, incident_facts
    if city not in graph.coords:
        raise SystemExit(f"unknown city: {city}")
    facts = incident_facts(kind, graph.tags[city], people)
    print(f"facts: {', '.join(sorted(facts)) or 'none'}")
    for name, proof in explain(facts).items():
        if proof is None:
            print(f"{name}: does not fire")
        else:
            print(f"{name}: fires")
            for line in proof:
                print("   ", line)


def interpret(graph, text, use_llm):
    """Show how the prompt engine reads a scenario, as structured JSON."""
    import json
    from aegis.core.prompt_engine.parser import describe
    from aegis.core.prompt_engine.scenario_generator import build_scenario
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
    ap.add_argument("--fairness", action="store_true",
                    help="response time per city for one standard incident; writes results/fairness.csv")
    ap.add_argument("--explain", nargs=3, metavar=("TYPE", "CITY", "PEOPLE"),
                    help="show which knowledge rules fire for an incident, with the proof, e.g. "
                         "--explain Fire Jaipur 60")
    args = ap.parse_args()
    if args.analyze:
        return analyze()
    if args.fairness:
        return fairness()
    graph = CityGraph.load()
    if args.explain:
        return explain_rules(graph, args.explain[0], args.explain[1], int(args.explain[2]))
    if args.parse:
        interpret(graph, args.parse, args.llm)
    elif args.compare:
        compare(graph, *args.compare)
    else:
        from aegis.desktop.pygame_ui import App
        App(graph, use_llm=args.llm).run()


if __name__ == "__main__":
    main()
