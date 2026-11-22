import unittest

from aegis.core.simulation.fairness import fairness_rows, summary


class FairnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fairness_rows()
        cls.by_city = {r["city"]: r for r in cls.rows}

    def test_every_city_is_served(self):
        self.assertEqual(len(self.rows), 14)
        self.assertTrue(all(r["response_h"] is not None for r in self.rows))

    def test_base_city_responds_immediately(self):
        self.assertEqual(self.by_city["Delhi"]["response_h"], 0.0)

    def test_response_grows_with_distance_from_base(self):
        self.assertGreater(summary(self.rows)["distance_response_correlation"], 0.95)
        self.assertGreater(self.by_city["Kota"]["response_h"],
                           self.by_city["Agra"]["response_h"])

    def test_flags_follow_the_median_ratio(self):
        flagged = summary(self.rows)["flagged"]
        self.assertIn("Kota", flagged)
        self.assertNotIn("Gurugram", flagged)


if __name__ == "__main__":
    unittest.main()
