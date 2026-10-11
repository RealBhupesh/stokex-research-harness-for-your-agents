import unittest

from stockex.backtest.statistics import (
    MIN_TRADES, assess, cluster_bootstrap_lower_bound, fold_stability,
)


def trades(rs, days_per_trade=1, start_day=0):
    out = []
    for index, r in enumerate(rs):
        day = start_day + index // days_per_trade
        out.append({"signal_date": f"2026-{1 + day // 28:02d}-{1 + day % 28:02d}", "r_multiple": r, "symbol": f"S{index}"})
    return out


class StatisticsTests(unittest.TestCase):
    def test_strong_steady_edge_is_proven(self):
        result = assess(trades([1.2, -0.4] * 40), hypotheses=9, label="steady")
        self.assertEqual(result["status"], "PROVEN", result["reasons"])
        self.assertGreater(result["expectancy_lower_bound"], 0)
        self.assertAlmostEqual(result["confidence"], 1 - 0.05 / 9, places=5)

    def test_thin_noisy_edge_fails_the_bound(self):
        noisy = [3.0, -1.0, -1.0, -1.0, 2.2, -1.0] * 6
        result = assess(trades(noisy), hypotheses=9, label="noisy")
        self.assertIn("Lower", " ".join(result["reasons"]))

    def test_clustered_wins_count_as_one_day(self):
        # 30 wins on one day and 30 small losses spread out: the mean is positive, but it hinges on one day.
        clustered = trades([2.0] * 30, days_per_trade=30) + trades([-0.3] * 30, start_day=1)
        self.assertIsNone(cluster_bootstrap_lower_bound(trades([1.0] * 5, days_per_trade=5), 0.05))
        self.assertEqual(assess(clustered, 1, "clustered")["status"], "UNPROVEN")

    def test_one_lucky_stretch_fails_fold_stability(self):
        lucky = [3.0] * 10 + [-0.2] * 30
        stability = fold_stability(trades(lucky))
        self.assertEqual(len(stability["folds"]), 4)
        self.assertLess(stability["positive_share"], 0.6)
        self.assertIn("folds", " ".join(assess(trades(lucky), 1, "lucky")["reasons"]))

    def test_too_few_trades(self):
        result = assess(trades([1.0] * (MIN_TRADES - 1)), 1, "few")
        self.assertTrue(result["reasons"][0].startswith("Only"))

    def test_bootstrap_is_deterministic(self):
        sample = trades([1.0, -0.5, 0.3] * 20)
        self.assertEqual(cluster_bootstrap_lower_bound(sample, 0.01, label="x"),
                         cluster_bootstrap_lower_bound(sample, 0.01, label="x"))


if __name__ == "__main__":
    unittest.main()
