import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis.core.ai.planning import ESCALATE_EVERY_H, escalate
from aegis.core.ai.rules import apply_rules
from aegis.core.environment.city import CityGraph
from aegis.core.environment.incidents import Incident
from aegis.core.simulation.engine import Simulation


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.graph = CityGraph.load()

    def fire(self, inc):
        return [(i.id, r.name) for i, r in apply_rules([inc], self.graph)]

    def test_fire_at_fuel_depot_goes_to_max_severity(self):
        inc = Incident("Fire", "Panipat", severity=2, people_affected=10)
        self.assertEqual(self.fire(inc), [(inc.id, "fire_at_fuel_depot")])
        self.assertEqual(inc.severity, 5)

    def test_fire_elsewhere_untouched(self):
        inc = Incident("Fire", "Alwar", severity=2, people_affected=10)
        self.assertEqual(self.fire(inc), [])
        self.assertEqual(inc.severity, 2)

    def test_medical_at_hospital_and_mass_casualty_stack(self):
        inc = Incident("Medical", "Delhi", severity=2, people_affected=150)
        self.assertEqual([n for _, n in self.fire(inc)], ["medical_at_hospital", "mass_casualty"])
        self.assertEqual(inc.severity, 4)

    def test_tourist_hub_accident_raises_headcount(self):
        inc = Incident("Accident", "Agra", severity=3, people_affected=10)
        self.fire(inc)
        self.assertEqual(inc.people_affected, 60)

    def test_rules_fire_once_per_incident(self):
        inc = Incident("Medical", "Delhi", severity=2, people_affected=10)
        self.fire(inc)
        self.assertEqual(self.fire(inc), [])
        self.assertEqual(inc.severity, 3)

    def test_severity_never_exceeds_cap(self):
        inc = Incident("Medical", "Delhi", severity=5, people_affected=500)
        self.fire(inc)
        self.assertEqual(inc.severity, 5)


class EscalationTests(unittest.TestCase):
    def test_escalates_every_interval_up_to_cap(self):
        inc = Incident("Fire", "Alwar", severity=3, time_reported=1.0)
        self.assertEqual(escalate([inc], 1.0 + ESCALATE_EVERY_H - 0.1), [])
        self.assertEqual(escalate([inc], 1.0 + ESCALATE_EVERY_H), [inc])
        self.assertEqual(inc.severity, 4)
        self.assertEqual(escalate([inc], 1.0 + ESCALATE_EVERY_H + 0.5), [])   # timer restarted
        self.assertEqual(escalate([inc], 1.0 + 2 * ESCALATE_EVERY_H), [inc])
        self.assertEqual(escalate([inc], 1.0 + 3 * ESCALATE_EVERY_H), [])     # capped at 5
        self.assertEqual(inc.severity, 5)


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.sim = Simulation(CityGraph.load())

    def test_rules_apply_on_report_before_dispatch(self):
        inc = self.sim.report("Fire", "Panipat", severity=2, people=10)
        self.assertEqual(inc.severity, 5)
        self.assertTrue(any("fire_at_fuel_depot" in e for e in self.sim.events))

    def test_waiting_incident_escalates_in_simulation(self):
        self.sim.set_road("Jaipur", "Ajmer", True)
        self.sim.set_road("Kota", "Ajmer", True)
        inc = self.sim.report("Accident", "Ajmer", severity=2, people=10)
        self.assertEqual(inc.status, "active")
        for _ in range(45):
            self.sim.step(0.05)                 # 2.25 h
        self.assertEqual(inc.severity, 3)
        self.assertTrue(any("escalated" in e for e in self.sim.events))


if __name__ == "__main__":
    unittest.main()
