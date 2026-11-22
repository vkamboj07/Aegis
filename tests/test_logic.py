import itertools
import unittest

from aegis.core.ai.logic import (RULE_CLAUSES, explain, incident_facts, kb_clauses, prove, refute)
from aegis.core.ai.rules import RULES
from aegis.core.environment.incidents import Incident

UNIVERSE = {"Fire", "Medical", "Accident", "FuelDepot", "Hospital", "TouristHub",
            "People100", "People60"}
TAGS = ("fuel_depot", "hospital", "tourist_hub")


class ResolutionTests(unittest.TestCase):
    def test_modus_ponens_is_entailed(self):
        kb = [frozenset(["p"]), frozenset(["~p", "q"])]     # p, p -> q
        self.assertEqual(refute(kb, "q")[0], True)

    def test_unsupported_goal_is_not_entailed(self):
        kb = [frozenset(["p"])]
        self.assertEqual(refute(kb, "q")[0], False)


class RuleBaseTests(unittest.TestCase):
    def test_backward_chaining_gives_a_proof_chain(self):
        lines = prove("fire_at_fuel_depot", {"Fire", "FuelDepot"})
        self.assertIsNotNone(lines)
        self.assertTrue(lines[-1].startswith("fire_at_fuel_depot because"))

    def test_no_proof_without_the_facts(self):
        self.assertIsNone(prove("fire_at_fuel_depot", {"Fire"}))

    def test_negation_as_failure_in_crowded_hub(self):
        self.assertIsNotNone(prove("crowded_tourist_hub", {"Accident", "TouristHub"}))
        self.assertIsNone(prove("crowded_tourist_hub",
                                {"Accident", "TouristHub", "People60"}))

    def test_explain_lists_every_rule(self):
        explained = explain({"Medical", "Hospital", "People100"})
        self.assertEqual(set(explained), {name for name, _ in RULE_CLAUSES})
        self.assertIsNotNone(explained["medical_at_hospital"])
        self.assertIsNone(explained["fire_at_fuel_depot"])

    def test_logic_agrees_with_python_rules_on_every_situation(self):
        """The propositional rules, checked by two methods (backward chaining and resolution),
        must give the same answer as the Python rule functions for every combination of
        incident type, city facilities and number of people."""
        checked = 0
        for kind, tags_raw, people in itertools.product(
                ["Fire", "Medical", "Accident", "Other"],
                [set(c) for n in range(len(TAGS) + 1) for c in itertools.combinations(TAGS, n)],
                [10, 60, 100]):
            facts = incident_facts(kind, tags_raw, people)
            clauses = kb_clauses(facts, UNIVERSE)
            incident = Incident(kind, "X", severity=3, people_affected=people)
            for rule in RULES:
                python_fires = rule.when(incident, frozenset(tags_raw))
                by_chaining = prove(rule.name, facts) is not None
                by_resolution = refute(clauses, rule.name)[0]
                self.assertEqual(by_chaining, python_fires,
                                 f"{rule.name} {kind} {tags_raw} {people}")
                self.assertEqual(by_resolution, python_fires,
                                 f"{rule.name} {kind} {tags_raw} {people}")
                checked += 1
        self.assertEqual(checked, 4 * 8 * 3 * len(RULES))


if __name__ == "__main__":
    unittest.main()
