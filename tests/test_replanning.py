import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from environment.city import CityGraph
from environment.events import EventQueue
from simulation.engine import Simulation


def run(sim, hours, dt=0.05):
    for _ in range(round(hours / dt)):
        sim.step(dt)


class EventQueueTests(unittest.TestCase):
    def test_pops_due_events_in_time_order(self):
        q = EventQueue()
        q.schedule(3.0, "road_closure", edge=["A", "B"])
        q.schedule(1.0, "new_incident")
        q.schedule(1.0, "road_reopen")
        self.assertEqual([e.kind for e in q.pop_due(2.0)], ["new_incident", "road_reopen"])
        self.assertEqual(len(q), 1)
        self.assertEqual(q.pop_due(2.5), [])

    def test_load_scenario(self):
        q = EventQueue()
        q.load_scenario("demo_replan", offset=1.0)
        first, second = q.pop_due(10)
        self.assertEqual((first.time, first.kind), (1.0, "new_incident"))
        self.assertEqual((second.time, second.kind), (3.0, "road_closure"))
        self.assertEqual(second.data["edge"], ["Jaipur", "Ajmer"])


class ReplanningTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def fire_in_ajmer(self):
        inc = self.sim.report("Fire", "Ajmer", 5, 200)
        v = self.sim.vehicle_for(inc)
        self.assertEqual(v.path, ["Delhi", "Gurugram", "Alwar", "Jaipur", "Ajmer"])
        return inc, v

    def test_closure_ahead_reroutes_from_next_junction(self):
        inc, v = self.fire_in_ajmer()
        run(self.sim, 1.0)                              # 60 km: on Gurugram-Alwar
        self.sim.set_road("Jaipur", "Ajmer", True)
        self.sim.step(0.05)
        best, options = v.pending
        self.assertEqual(options[best][0], ["Alwar", "Jaipur", "Kota", "Ajmer"])
        self.assertFalse(v.backtrack)
        run(self.sim, 14)
        self.assertEqual(inc.status, "resolved")
        self.assertEqual(v.replans, 1)
        job = self.sim.races[-1]                        # the route actually driven to the fire
        self.assertEqual(job.options[job.chosen][0], ["Alwar", "Jaipur", "Kota", "Ajmer"])

    def test_replan_starts_a_new_race_from_the_junction(self):
        inc, v = self.fire_in_ajmer()
        run(self.sim, 1.0)
        self.sim.set_road("Jaipur", "Ajmer", True)
        run(self.sim, 2.5)                              # past Alwar, on the new route
        first, second = self.sim.races
        self.assertTrue(first.ended)
        self.assertEqual(second.options[second.chosen][0][0], "Alwar")

    def test_closure_under_the_wheels_makes_vehicle_turn_back(self):
        inc, v = self.fire_in_ajmer()
        run(self.sim, 1.0)
        self.sim.set_road("Gurugram", "Alwar", True)
        self.sim.step(0.05)
        self.assertTrue(v.backtrack)
        before = v.seg_progress
        self.sim.step(0.05)
        self.assertLess(v.seg_progress, before)         # driving back towards Gurugram
        run(self.sim, 20)
        self.assertEqual(inc.status, "resolved")
        route = self.sim.races[-1].options[self.sim.races[-1].chosen][0]
        self.assertEqual(route[0], "Gurugram")
        self.assertNotIn(("Gurugram", "Alwar"), list(zip(route, route[1:])))

    def test_unreachable_incident_is_requeued_then_served_after_reopen(self):
        inc, v = self.fire_in_ajmer()
        run(self.sim, 1.0)
        self.sim.set_road("Jaipur", "Ajmer", True)
        self.sim.set_road("Kota", "Ajmer", True)
        run(self.sim, 5)
        self.assertEqual(inc.status, "active")
        self.assertIn(v.status, ("returning", "idle"))
        self.sim.set_road("Kota", "Ajmer", False)
        self.sim.step(0.05)
        self.assertEqual(inc.status, "assigned")
        run(self.sim, 30)
        self.assertEqual(inc.status, "resolved")

    def test_incident_in_unreachable_city_waits(self):
        self.sim.set_road("Jaipur", "Ajmer", True)
        self.sim.set_road("Kota", "Ajmer", True)
        inc = self.sim.report("Fire", "Ajmer", 5, 200)
        self.assertEqual(inc.status, "active")

    def test_scripted_demo_runs_to_completion(self):
        self.sim.queue.load_scenario("demo_replan")
        run(self.sim, 20)
        self.assertEqual(self.sim.incidents[0].status, "resolved")
        self.assertEqual(sum(v.replans for v in self.sim.fleet), 1)
        self.assertTrue(any("REPLANNING" in e for e in self.sim.events))


if __name__ == "__main__":
    unittest.main()
