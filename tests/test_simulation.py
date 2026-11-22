import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.heuristics import rank, urgency
from ai.routing import plan_routes
from environment.city import CityGraph
from environment.incidents import Incident
from simulation.engine import ON_SCENE_H, REPAIR_H, Simulation


def run(sim, hours, dt=0.05):
    for _ in range(round(hours / dt)):
        sim.step(dt)


class UrgencyTests(unittest.TestCase):
    def test_formula(self):
        inc = Incident("Fire", "Delhi", severity=4, people_affected=50, time_reported=0)
        self.assertEqual(urgency(inc, now=0), 200)
        self.assertEqual(urgency(inc, now=0.5), 200)    # elapsed floored at 1 h
        self.assertEqual(urgency(inc, now=4), 50)

    def test_rank_orders_by_urgency(self):
        a = Incident("Fire", "Delhi", 2, 10)
        b = Incident("Medical", "Agra", 5, 100)
        self.assertEqual(rank([a, b], 0), [b, a])


class RoutingTests(unittest.TestCase):
    def test_best_route_is_shortest_then_fewest_nodes(self):
        best, options = plan_routes(CityGraph.load(), "Delhi", "Kota")
        self.assertEqual(set(options), {"A*", "UCS", "BFS", "DFS"})
        self.assertEqual(best, "A*")
        shortest = min(o[1] for o in options.values())
        self.assertEqual(options[best][1], shortest)
        self.assertLessEqual(options[best][2], options["UCS"][2])
        self.assertGreater(options["DFS"][1], shortest)            # DFS: 812 km vs 582

    def test_unreachable_goal(self):
        graph = CityGraph.load()
        graph.set_closed("Jaipur", "Ajmer")
        graph.set_closed("Kota", "Ajmer")
        best, options = plan_routes(graph, "Delhi", "Ajmer")
        self.assertEqual(options[best][0], [])


class FleetTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def test_every_vehicle_starts_idle_at_the_depot(self):
        self.assertEqual({(v.location, v.status) for v in self.sim.fleet}, {("Delhi", "idle")})
        self.assertEqual(len(self.sim.fleet), 5)

    def test_incident_gets_one_vehicle_then_it_returns_to_base(self):
        inc = self.sim.report("Fire", "Jaipur", 4, 50)
        busy = [v for v in self.sim.fleet if not v.free]
        self.assertEqual(len(busy), 1)
        v = busy[0]
        self.assertEqual((v.kind, v.algorithm, v.path),
                         ("Fire Truck", "A*", ["Delhi", "Gurugram", "Alwar", "Jaipur"]))
        run(self.sim, 332 / 60 + 0.1)
        self.assertEqual((inc.status, v.status, v.location), ("resolved", "on_scene", "Jaipur"))
        run(self.sim, ON_SCENE_H)
        self.assertEqual(v.status, "returning")
        run(self.sim, 332 / 60 + 0.2)
        self.assertEqual((v.status, v.location), ("idle", "Delhi"))

    def test_incident_at_the_depot_resolves_immediately(self):
        inc = self.sim.report("Medical", "Delhi", 3, 10)
        self.assertEqual(inc.status, "resolved")

    def test_vehicles_only_get_compatible_incidents(self):
        for kind, city in [("Fire", "Jaipur"), ("Medical", "Kota"), ("Accident", "Ajmer")]:
            inc = self.sim.report(kind, city, 3, 10)
            self.assertTrue(self.sim.vehicle_for(inc).can_serve(kind))


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def test_simultaneous_incidents_are_served_in_priority_order(self):
        # three fires at once, two fire trucks: the least urgent one waits
        low, high, mid = self.sim.report_batch([
            dict(kind="Fire", location="Meerut", severity=2, people=10),
            dict(kind="Fire", location="Jaipur", severity=4, people=60),
            dict(kind="Fire", location="Agra", severity=3, people=30)])
        self.assertEqual([i.status for i in (low, mid, high)], ["active", "assigned", "assigned"])
        run(self.sim, 30)
        self.assertEqual(low.status, "resolved")                   # served once a truck frees up

    def test_more_incidents_than_vehicles_all_resolve_eventually(self):
        kinds = ["Fire", "Medical", "Accident", "Fire", "Fire", "Medical"]
        cities = ["Jaipur", "Kota", "Ajmer", "Chandigarh", "Gwalior", "Agra"]
        incs = self.sim.report_batch([dict(kind=k, location=c) for k, c in zip(kinds, cities)])
        self.assertTrue(any(i.status == "active" for i in incs))
        run(self.sim, 60)
        self.assertTrue(all(i.status == "resolved" for i in incs))


class ScenarioTests(unittest.TestCase):
    def test_same_time_scenario_incidents_are_allocated_by_priority(self):
        sim = Simulation(CityGraph.load())
        sim.queue.load_scenario("showcase")
        sim.step(0.05)
        meerut = next(i for i in sim.incidents if i.location == "Meerut")
        self.assertEqual(meerut.status, "active")                 # lowest-priority fire waits
        self.assertEqual(sum(i.status == "assigned" for i in sim.incidents), 3)

    def test_scripted_breakdown_event(self):
        sim = Simulation(CityGraph.load())
        sim.queue.load_scenario("showcase")
        run(sim, 2.6)
        self.assertEqual(sim.vehicle("Fire Truck 2").status, "broken")
        run(sim, 40)
        self.assertTrue(all(i.status == "resolved" for i in sim.incidents))

    def test_random_disruptions_happen_and_everything_still_resolves(self):
        sim = Simulation(CityGraph.load(), seed=3)
        sim.random_events = True
        sim.report_batch([dict(kind="Fire", location="Jaipur"), dict(kind="Medical", location="Kota"),
                          dict(kind="Accident", location="Agra")])
        run(sim, 60)
        self.assertTrue(any(r["event"] == "random_event" for r in sim.records))
        self.assertTrue(all(i.status == "resolved" for i in sim.incidents))


class RaceTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def test_dispatch_starts_a_race_with_a_ghost_per_other_algorithm(self):
        self.sim.report("Fire", "Agra", 3, 10)
        race = self.sim.latest_race()
        self.assertEqual(race.chosen, "A*")
        self.assertEqual(sorted(g.algorithm for g in race.ghosts), ["BFS", "DFS", "UCS"])
        self.assertEqual(race.destination, "Agra")

    def test_ghosts_move_at_vehicle_speed_and_slower_routes_arrive_later(self):
        self.sim.report("Fire", "Agra", 3, 10)                     # A* 203 km, DFS 352 km
        race = self.sim.latest_race()
        run(self.sim, 8)
        dfs = next(g for g in race.ghosts if g.algorithm == "DFS")
        self.assertIsNotNone(race.arrived_at)
        self.assertGreater(dfs.arrived_at, race.arrived_at + 2)
        self.assertFalse(race.running)


class BreakdownTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def test_breakdown_requeues_incident_and_another_vehicle_takes_it(self):
        inc = self.sim.report("Fire", "Jaipur", 4, 50)
        first = self.sim.vehicle_for(inc)
        run(self.sim, 1.0)
        self.assertTrue(self.sim.break_down(first.name))
        self.assertEqual(first.status, "broken")
        self.sim.step(0.05)                                         # CSP re-allocates
        second = self.sim.vehicle_for(inc)
        self.assertIsNotNone(second)
        self.assertNotEqual(second.name, first.name)
        self.assertTrue(self.sim.races[0].ended)
        run(self.sim, REPAIR_H)
        self.assertIn(first.status, ("returning", "idle"))
        run(self.sim, 12)
        self.assertEqual(inc.status, "resolved")
        self.assertEqual((first.status, first.location), ("idle", "Delhi"))

    def test_only_a_driving_vehicle_can_break_down(self):
        self.assertFalse(self.sim.break_down("Fire Truck 1"))
        self.assertFalse(self.sim.break_down("No Such Truck"))


class RetaskTests(unittest.TestCase):
    def test_returning_vehicle_is_retasked_if_it_is_closest(self):
        sim = Simulation(CityGraph.load())
        sim.report("Fire", "Agra", 3, 10)                          # Delhi-Faridabad-Mathura-Agra
        truck = sim.vehicle("Fire Truck 1")
        run(sim, 203 / 60 + ON_SCENE_H + 0.5)                      # heading home, 30 km out of Agra
        self.assertEqual(truck.status, "returning")
        inc = sim.report("Fire", "Mathura", 3, 10)
        self.assertEqual(sim.vehicle_for(inc).name, "Fire Truck 1")  # 28 km vs 145 km from base
        run(sim, 1)
        self.assertEqual(inc.status, "resolved")


if __name__ == "__main__":
    unittest.main()
