import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portfolio_execution import candidate_opportunity_cost, execution_estimate, position_risk_budget


class OpportunityCostTests(unittest.TestCase):
    def test_compares_candidate_with_best_named_alternative(self):
        result = candidate_opportunity_cost(0.18, [
            {"name": "Nifty 50", "expected_return": 0.10},
            {"name": "Peer B", "expected_return": 0.22},
        ])
        self.assertEqual(result["best_alternative"], "Peer B")
        self.assertAlmostEqual(result["candidate_excess_return"], -0.04)
        self.assertFalse(result["candidate_leads"])


class ExecutionTests(unittest.TestCase):
    def test_estimates_friction_and_exit_capacity(self):
        result = execution_estimate(
            order_value=1_000_000,
            average_daily_traded_value=4_000_000,
            spread_bps=20,
            slippage_bps=15,
            fees_bps=5,
            participation_rate=0.10,
        )
        self.assertAlmostEqual(result["one_way_friction_fraction"], 0.004)
        self.assertAlmostEqual(result["estimated_one_way_friction"], 4_000)
        self.assertEqual(result["minimum_exit_sessions"], 3)
        self.assertAlmostEqual(result["daily_capacity"], 400_000)

    def test_rejects_invalid_liquidity_or_cost_inputs(self):
        invalid = [
            {"order_value": 0, "average_daily_traded_value": 1_000, "spread_bps": 1, "slippage_bps": 1, "fees_bps": 1},
            {"order_value": 1_000, "average_daily_traded_value": 0, "spread_bps": 1, "slippage_bps": 1, "fees_bps": 1},
            {"order_value": 1_000, "average_daily_traded_value": 1_000, "spread_bps": -1, "slippage_bps": 1, "fees_bps": 1},
            {"order_value": 1_000, "average_daily_traded_value": 1_000, "spread_bps": 1, "slippage_bps": 1, "fees_bps": 1, "participation_rate": 1.1},
        ]
        for inputs in invalid:
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                execution_estimate(**inputs)


class PositionRiskTests(unittest.TestCase):
    def test_sizes_by_explicit_portfolio_loss_budget(self):
        result = position_risk_budget(
            portfolio_value=500_000,
            max_loss_fraction=0.01,
            entry_price=200,
            invalidation_price=180,
        )
        self.assertEqual(result["shares"], 250)
        self.assertEqual(result["position_value"], 50_000)
        self.assertEqual(result["planned_loss"], 5_000)
        self.assertAlmostEqual(result["portfolio_weight"], 0.10)


if __name__ == "__main__":
    unittest.main()
