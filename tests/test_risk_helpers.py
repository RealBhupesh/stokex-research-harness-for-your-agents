import math
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_helpers import liquidity_exit_days, market_risk_metrics


class MarketRiskMetricsTests(unittest.TestCase):
    def test_calculates_backward_looking_market_risk_metrics(self):
        result = market_risk_metrics(
            periodic_returns=[-0.10, 0.05, -0.20, 0.10],
            benchmark_returns=[-0.05, 0.02, -0.10, 0.04],
            periods_per_year=4,
            confidence=0.75,
        )

        self.assertEqual(result["n_periods"], 4)
        self.assertAlmostEqual(result["annualized_volatility"], 0.2753785274)
        self.assertAlmostEqual(result["beta"], 2.1342685371)
        self.assertAlmostEqual(result["maximum_drawdown"], -0.244)
        self.assertAlmostEqual(result["annualized_downside_deviation"], math.sqrt(0.05))
        self.assertAlmostEqual(result["historical_var_loss"], 0.10)
        self.assertAlmostEqual(result["historical_cvar_loss"], 0.15)
        self.assertAlmostEqual(result["worst_period_loss"], 0.20)
        self.assertIn("backward-looking", result["warning"])

    def test_rejects_unusable_series_or_confidence(self):
        invalid_cases = [
            {"periodic_returns": [], "benchmark_returns": []},
            {"periodic_returns": [0.01], "benchmark_returns": [0.01, 0.02]},
            {"periodic_returns": [-1.0], "benchmark_returns": [0.0]},
            {"periodic_returns": [0.01], "benchmark_returns": [0.01], "confidence": 1.0},
        ]

        for inputs in invalid_cases:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                market_risk_metrics(**inputs)


class LiquidityExitTests(unittest.TestCase):
    def test_estimates_exit_sessions_at_a_participation_cap(self):
        result = liquidity_exit_days(
            position_value=1_000_001,
            average_daily_traded_value=2_000_000,
            max_participation_rate=0.10,
        )

        self.assertAlmostEqual(result["raw_trading_days"], 5.000005)
        self.assertEqual(result["minimum_whole_trading_sessions"], 6)
        self.assertEqual(result["daily_exit_capacity"], 200_000)
        self.assertIn("not a guarantee", result["warning"])

    def test_rejects_nonpositive_inputs_and_invalid_participation(self):
        invalid_cases = [
            {"position_value": 0, "average_daily_traded_value": 1_000},
            {"position_value": 1_000, "average_daily_traded_value": 0},
            {"position_value": 1_000, "average_daily_traded_value": 1_000, "max_participation_rate": 0},
            {"position_value": 1_000, "average_daily_traded_value": 1_000, "max_participation_rate": 1.1},
        ]

        for inputs in invalid_cases:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                liquidity_exit_days(**inputs)


if __name__ == "__main__":
    unittest.main()
