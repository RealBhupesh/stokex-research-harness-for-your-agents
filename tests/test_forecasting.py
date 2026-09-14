import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from forecasting import driver_forecast, estimate_revision, guidance_score, scenario_distribution


class DriverForecastTests(unittest.TestCase):
    def test_builds_multiplicative_driver_bridge(self):
        result = driver_forecast(100, [
            {"name": "volume", "impact": 0.10},
            {"name": "price", "impact": -0.05},
        ])
        self.assertAlmostEqual(result["forecast_value"], 104.5)
        self.assertEqual([row["name"] for row in result["bridge"]], ["volume", "price"])

    def test_rejects_unnamed_or_nonfinite_drivers(self):
        for drivers in ([{"impact": 0.1}], [{"name": "x", "impact": float("inf")}], []):
            with self.subTest(drivers=drivers), self.assertRaises(ValueError):
                driver_forecast(100, drivers)


class EstimateRevisionTests(unittest.TestCase):
    def test_labels_revision_direction(self):
        self.assertEqual(estimate_revision(100, 110)["direction"], "UP")
        self.assertEqual(estimate_revision(100, 90)["direction"], "DOWN")
        self.assertEqual(estimate_revision(100, 100)["direction"], "UNCHANGED")


class ScenarioTests(unittest.TestCase):
    def test_calculates_probability_weighted_value_and_loss_probability(self):
        result = scenario_distribution(100, [
            {"name": "bear", "value": 50, "probability": 0.25},
            {"name": "base", "value": 120, "probability": 0.50},
            {"name": "bull", "value": 200, "probability": 0.25},
        ])
        self.assertAlmostEqual(result["expected_value"], 122.5)
        self.assertAlmostEqual(result["expected_return"], 0.225)
        self.assertAlmostEqual(result["probability_of_loss"], 0.25)
        self.assertAlmostEqual(result["maximum_scenario_downside"], -0.5)
        self.assertAlmostEqual(result["maximum_scenario_upside"], 1.0)

    def test_allows_ranges_without_inventing_probabilities(self):
        result = scenario_distribution(100, [
            {"name": "bear", "value": 70},
            {"name": "bull", "value": 160},
        ])
        self.assertIsNone(result["expected_value"])
        self.assertIsNone(result["probability_of_loss"])

    def test_rejects_partial_or_inconsistent_probabilities(self):
        invalid = [
            [{"name": "bear", "value": 70, "probability": 0.5}, {"name": "bull", "value": 160}],
            [{"name": "bear", "value": 70, "probability": 0.2}, {"name": "bull", "value": 160, "probability": 0.2}],
        ]
        for scenarios in invalid:
            with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                scenario_distribution(100, scenarios)


class GuidanceScoreTests(unittest.TestCase):
    def test_scores_management_guidance_without_endorsement(self):
        result = guidance_score([
            {"metric": "revenue", "forecast": 100, "actual": 102, "tolerance": 0.05},
            {"metric": "margin", "forecast": 20, "actual": 18, "tolerance": 0.05},
        ])
        self.assertEqual(result["records"], 2)
        self.assertEqual(result["within_range_count"], 1)
        self.assertAlmostEqual(result["within_range_rate"], 0.5)
        self.assertAlmostEqual(result["mean_signed_error_fraction"], -0.04)


if __name__ == "__main__":
    unittest.main()
