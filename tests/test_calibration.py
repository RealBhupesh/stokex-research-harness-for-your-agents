import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from calibration import forecast_error, process_score, validate_transition


class ThesisTransitionTests(unittest.TestCase):
    def test_accepts_dated_evidence_trigger_for_valid_transition(self):
        result = validate_transition("ACTIVE", "WEAKENED", {
            "id": "T1",
            "occurred_at": "2026-09-13T10:00:00+05:30",
            "source_id": "S4",
            "reason": "Volume guidance reduced",
        })
        self.assertTrue(result["valid"])

    def test_rejects_silent_or_impossible_status_change(self):
        self.assertFalse(validate_transition("ACTIVE", "WEAKENED", {})["valid"])
        self.assertFalse(validate_transition("CLOSED", "ACTIVE", {
            "id": "T2", "occurred_at": "2026-09-13T10:00:00+05:30", "source_id": "S4", "reason": "Changed mind"
        })["valid"])


class ForecastErrorTests(unittest.TestCase):
    def test_reports_direction_and_scaled_error(self):
        result = forecast_error(120, 100)
        self.assertEqual(result["direction"], "OVER")
        self.assertAlmostEqual(result["signed_error"], 20)
        self.assertAlmostEqual(result["absolute_percentage_error"], 0.20)


class ProcessScoreTests(unittest.TestCase):
    def test_aggregates_closed_records_and_error_categories(self):
        result = process_score([
            {"decision_outcome": "SUCCESS", "forecast_error_fraction": -0.10, "process_errors": ["CATALYST"]},
            {"decision_outcome": "FAILURE", "forecast_error_fraction": 0.30, "process_errors": ["FORECAST", "RISK"]},
            {"decision_outcome": "OPEN", "forecast_error_fraction": 0.05, "process_errors": []},
        ])
        self.assertEqual(result["closed_records"], 2)
        self.assertAlmostEqual(result["success_rate"], 0.5)
        self.assertAlmostEqual(result["mean_absolute_forecast_error"], 0.20)
        self.assertEqual(result["process_error_counts"], {"CATALYST": 1, "FORECAST": 1, "RISK": 1})
        self.assertTrue(result["small_sample_warning"])


if __name__ == "__main__":
    unittest.main()
