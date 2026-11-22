import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aegis.core.ai.csp import allocate


def costs(table):
    return lambda var, val: table[var, val]


class CspTests(unittest.TestCase):
    def test_no_double_booking(self):
        r = allocate({1: 10, 2: 5}, {1: ["a"], 2: ["a"]}, costs({(1, "a"): 1, (2, "a"): 1}))
        self.assertEqual(r.assignment, {1: "a"})        # higher weight wins the shared vehicle

    def test_beats_greedy(self):
        # Greedy gives incident 1 its cheapest vehicle "a" and strands incident 2.
        table = {(1, "a"): 1, (1, "b"): 5, (2, "a"): 2}
        r = allocate({1: 10, 2: 9}, {1: ["a", "b"], 2: ["a"]}, costs(table))
        self.assertEqual(r.assignment, {1: "b", 2: "a"})

    def test_minimises_total_cost_among_full_assignments(self):
        table = {(1, "a"): 1, (1, "b"): 4, (2, "a"): 3, (2, "b"): 1}
        r = allocate({1: 5, 2: 5}, {1: ["a", "b"], 2: ["a", "b"]}, costs(table))
        self.assertEqual(r.assignment, {1: "a", 2: "b"})
        self.assertEqual(r.cost, 2)

    def test_empty_domain_is_left_unserved(self):
        r = allocate({1: 10, 2: 5}, {1: [], 2: ["a"]}, costs({(2, "a"): 1}))
        self.assertEqual(r.assignment, {2: "a"})

    def test_no_variables(self):
        r = allocate({}, {}, costs({}))
        self.assertEqual((r.assignment, r.cost), ({}, 0))

    def test_forward_checking_prunes(self):
        r = allocate({1: 10, 2: 5}, {1: ["a", "b"], 2: ["a", "b"]},
                     costs({(i, v): 1 for i in (1, 2) for v in "ab"}))
        self.assertGreater(r.pruned, 0)


if __name__ == "__main__":
    unittest.main()
