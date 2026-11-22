import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis.core.environment.city import CityGraph
from aegis.core.prompt_engine.llm import parse_with_llm
from aegis.core.prompt_engine.parser import parse, validate_events
from aegis.core.prompt_engine.scenario_generator import build_scenario, save_scenario, schedule
from aegis.core.simulation.engine import Simulation


def run(text):
    graph = CityGraph.load()
    return parse(text, graph.nodes, set(graph.roads))


def incident(events, i=0):
    return [e for e in events if e["type"] == "new_incident"][i]


class ParserTests(unittest.TestCase):
    def test_example_scenario(self):
        r = run("Major fire in Jaipur, 200 people affected. At 2 hours the Jaipur-Ajmer road closes.")
        self.assertEqual(r.events, [
            {"time": 0.0, "type": "new_incident", "incident_type": "Fire", "location": "Jaipur",
             "severity": 4, "people": 200},
            {"time": 2.0, "type": "road_closure", "edge": ["Jaipur", "Ajmer"]}])
        self.assertEqual(r.warnings, [])

    def test_two_incidents_in_one_sentence(self):
        r = run("Accident near Agra with 15 injured and a medical emergency in Kota.")
        a, m = incident(r.events, 0), incident(r.events, 1)
        self.assertEqual((a["incident_type"], a["location"], a["people"]), ("Accident", "Agra", 15))
        self.assertEqual((m["incident_type"], m["location"], m["people"]), ("Medical", "Kota", 10))

    def test_time_phrases(self):
        self.assertEqual(run("Fire in Delhi at 3 hours.").events[0]["time"], 3.0)
        self.assertEqual(run("After 90 minutes a stampede in Delhi.").events[0]["time"], 1.5)
        self.assertEqual(run("Fire in Delhi at t=1.5.").events[0]["time"], 1.5)
        r = run("Fire in Delhi at 2 hours. Accident in Agra. Medical emergency in Kota two hours later.")
        self.assertEqual([e["time"] for e in r.events], [2.0, 2.0, 4.0])

    def test_road_between_two_cities_and_reopen_refers_back(self):
        r = run("Fire in Panipat. Two hours later the road between Delhi and Panipat is blocked. "
                "After 5 hours the road reopens.")
        self.assertEqual([(e["time"], e["type"], e.get("edge")) for e in r.events[1:]],
                         [(2.0, "road_closure", ["Delhi", "Panipat"]),
                          (5.0, "road_reopen", ["Delhi", "Panipat"])])

    def test_list_continuation_and_trailing_refinement(self):
        r = run("Fires in Jaipur and Agra, severity 4.")
        self.assertEqual([(e["location"], e["severity"]) for e in r.events],
                         [("Jaipur", 4), ("Agra", 4)])

    def test_severity_words_and_number_words_and_aliases(self):
        e = run("Massive blaze in Gurgaon affecting fifty people")
        self.assertEqual((e.events[0]["location"], e.events[0]["severity"], e.events[0]["people"]),
                         ("Gurugram", 5, 50))
        self.assertEqual(run("A minor accident in Alwar.").events[0]["severity"], 2)
        self.assertEqual(run("Fire in Alwar, severity level 5.").events[0]["severity"], 5)

    def test_defaults(self):
        e = run("Fire in Alwar.").events[0]
        self.assertEqual((e["severity"], e["people"], e["time"]), (3, 10, 0.0))

    def test_unparseable_text_gives_warnings_not_events(self):
        for text in ("It was a sunny day in Jaipur.", "Heart attack in Atlantis.", ""):
            with self.subTest(text=text):
                r = run(text)
                self.assertEqual(r.events, [])
        self.assertTrue(run("Heart attack in Atlantis.").warnings)

    def test_nonexistent_road_is_rejected(self):
        r = run("The road between Jaipur and Chandigarh closes.")
        self.assertEqual(r.events, [])
        self.assertTrue(any("no direct road" in w for w in r.warnings))


class ValidateTests(unittest.TestCase):
    def setUp(self):
        g = CityGraph.load()
        self.cities, self.roads = g.nodes, set(g.roads)

    def test_normalises_and_clamps(self):
        clean, warnings = validate_events(
            [{"time": -4, "type": "new_incident", "incident_type": "fire", "location": "jaipur",
              "severity": 9, "people": 0}], self.cities, self.roads)
        self.assertEqual(clean, [{"time": 0.0, "type": "new_incident", "incident_type": "Fire",
                                  "location": "Jaipur", "severity": 5, "people": 1}])
        self.assertEqual(warnings, [])

    def test_drops_bad_events_and_sorts(self):
        clean, warnings = validate_events([
            {"time": 5, "type": "road_closure", "edge": ["Jaipur", "Ajmer"]},
            {"time": 1, "type": "new_incident", "incident_type": "Flood", "location": "Jaipur"},
            {"time": 1, "type": "teleport"},
            {"time": 0, "type": "new_incident", "incident_type": "Fire", "location": "Narnia"},
            {"time": 2, "type": "road_closure", "edge": ["Jaipur"]},
            {"time": 0, "type": "new_incident", "incident_type": "Fire", "location": "Agra"},
        ], self.cities, self.roads)
        self.assertEqual([e["time"] for e in clean], [0.0, 5.0])
        self.assertEqual(len(warnings), 4)


class FakeClient:
    """Stands in for anthropic.Anthropic(); records the request it receives."""
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="text", text=self.text)])


class LlmFallbackTests(unittest.TestCase):
    def setUp(self):
        self.graph = CityGraph.load()

    def test_reply_is_validated_with_the_same_rules(self):
        reply = ('Sure:\n```json\n{"events": [{"time": 1, "type": "new_incident", '
                 '"incident_type": "Fire", "location": "Kota", "severity": 4, "people": 30}, '
                 '{"time": 2, "type": "new_incident", "incident_type": "Fire", "location": "Mars"}]}\n```')
        client = FakeClient(reply)
        r = parse_with_llm("zzz", self.graph.nodes, set(self.graph.roads), client)
        self.assertEqual(r.method, "llm")
        self.assertEqual([e["location"] for e in r.events], ["Kota"])
        self.assertEqual(len(r.warnings), 1)
        self.assertEqual(client.calls[0]["messages"], [{"role": "user", "content": "zzz"}])
        self.assertIn("Kota", client.calls[0]["system"])

    def test_failures_return_none(self):
        args = ("x", self.graph.nodes, set(self.graph.roads))
        self.assertIsNone(parse_with_llm(*args, FakeClient("no json here")))
        self.assertIsNone(parse_with_llm(*args, FakeClient("{}", stop_reason="refusal")))
        broken = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: 1 / 0))
        self.assertIsNone(parse_with_llm(*args, broken))

    def test_fallback_only_runs_when_requested_and_needed(self):
        client = FakeClient('{"events": [{"time": 0, "type": "new_incident", '
                            '"incident_type": "Medical", "location": "Agra"}]}')
        off = build_scenario("gibberish", self.graph, use_llm=False, client=client)
        self.assertEqual((off["events"], client.calls), ([], []))
        on = build_scenario("gibberish", self.graph, use_llm=True, client=client)
        self.assertEqual((on["method"], len(on["events"])), ("llm", 1))
        rules_ok = build_scenario("Fire in Delhi.", self.graph, use_llm=True, client=client)
        self.assertEqual((rules_ok["method"], len(client.calls)), ("rules", 1))   # no extra call


class GeneratorTests(unittest.TestCase):
    def test_typed_scenario_runs_in_the_simulation(self):
        graph = CityGraph.load()
        sim = Simulation(graph)
        for _ in range(10):
            sim.step(0.1)                                    # sim already at t = 1.0
        scenario = build_scenario("Major fire in Ajmer, 200 people affected. "
                                  "At 2 hours the Jaipur-Ajmer road closes.", graph)
        schedule(sim, scenario)                              # times are relative to now
        for _ in range(400):
            sim.step(0.05)
        self.assertEqual(sim.incidents[0].status, "resolved")
        self.assertAlmostEqual(sim.incidents[0].time_reported, 1.0, delta=0.1)
        self.assertTrue(any(e["event"] == "road_closed" and abs(e["time_h"] - 3.0) < 0.1
                            for e in sim.records))

    def test_save_scenario_round_trip(self):
        scenario = build_scenario("Fire in Delhi.", CityGraph.load())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scenarios.json"
            path.write_text('{"existing": {"description": "x", "events": []}}')
            save_scenario("typed", scenario, path)
            data = json.loads(path.read_text())
        self.assertEqual(set(data), {"existing", "typed"})
        self.assertEqual(data["typed"]["events"][0]["location"], "Delhi")


if __name__ == "__main__":
    unittest.main()
