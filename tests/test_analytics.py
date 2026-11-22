import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simulation.recorder import BENCH_FIELDS, SIM_FIELDS, load_csv, save_csv
from simulation.runner import benchmark, run_all, run_scenario, scenario_rows

try:
    import matplotlib  # noqa: F401
except ImportError:
    matplotlib = None


class RecordTests(unittest.TestCase):
    def test_every_scenario_resolves_all_incidents(self):
        for name, sim in run_all().items():
            with self.subTest(scenario=name):
                self.assertTrue(sim.incidents)
                self.assertTrue(all(i.status == "resolved" for i in sim.incidents))

    def test_resolved_rows_carry_response_time(self):
        sim = run_scenario("single_fire")
        resolved = [r for r in sim.records if r["event"] == "resolved"]
        self.assertEqual(len(resolved), 1)
        inc = sim.incidents[0]
        self.assertAlmostEqual(resolved[0]["response_h"], inc.time_resolved - inc.time_reported, places=2)

    def test_dispatch_and_replan_rows_carry_search_metrics(self):
        sim = run_scenario("demo_replan")
        kinds = {r["event"]: r for r in sim.records}
        for kind in ("dispatch", "replan"):
            self.assertGreater(kinds[kind]["nodes_expanded"], 0)
            self.assertGreater(kinds[kind]["distance_km"], 0)
            self.assertIn(kinds[kind]["algorithm"], ("BFS", "DFS", "UCS", "A*"))

    def test_csv_round_trip(self):
        rows = scenario_rows({"single_fire": run_scenario("single_fire")})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "sim.csv"
            save_csv(rows, path, SIM_FIELDS)
            back = load_csv(path)
        self.assertEqual(len(back), len(rows))
        self.assertEqual({r["scenario"] for r in back}, {"single_fire"})
        self.assertEqual([r["event"] for r in back], [r["event"] for r in rows])


class BenchmarkTests(unittest.TestCase):
    def test_all_pairs_all_algorithms(self):
        rows = benchmark()
        self.assertEqual(len(rows), 14 * 13 * 4)
        best = {(r["start"], r["goal"]): r["distance_km"] for r in rows if r["algorithm"] == "UCS"}
        for r in rows:
            if r["algorithm"] in ("UCS", "A*"):
                self.assertAlmostEqual(r["distance_km"], best[r["start"], r["goal"]], places=1)
            else:
                self.assertGreaterEqual(r["distance_km"], best[r["start"], r["goal"]] - 0.05)

    def test_astar_expands_fewer_nodes_on_average(self):
        rows = benchmark()
        mean = {a: sum(r["nodes_expanded"] for r in rows if r["algorithm"] == a) / 182
                for a in ("BFS", "DFS", "UCS", "A*")}
        self.assertLess(mean["A*"], min(mean["BFS"], mean["DFS"], mean["UCS"]))

    def test_benchmark_csv_round_trip(self):
        rows = benchmark()[:8]
        with tempfile.TemporaryDirectory() as tmp:
            save_csv(rows, Path(tmp) / "b.csv", BENCH_FIELDS)
            self.assertEqual(len(load_csv(Path(tmp) / "b.csv")), 8)


@unittest.skipIf(matplotlib is None, "matplotlib not installed")
class ChartTests(unittest.TestCase):
    def test_make_all_writes_four_pngs_from_csv_rows(self):
        from visualization.charts import make_all
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            save_csv(benchmark(), tmp / "b.csv", BENCH_FIELDS)
            save_csv(scenario_rows(run_all()), tmp / "s.csv", SIM_FIELDS)
            paths = make_all(load_csv(tmp / "b.csv"), load_csv(tmp / "s.csv"), tmp)
            self.assertEqual(len(paths), 4)
            for p in paths:
                self.assertGreater(p.stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
