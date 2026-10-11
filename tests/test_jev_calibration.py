import unittest

from stockex.jev.calibration import MIN_JUDGED_TRADES, auc, brier, evaluate_jev, reliability


def trade(p, hit, r, setup="BREAKOUT_52W"):
    return {"jev_p": p, "t1_hit": hit, "r_multiple": r, "setup": setup}


def informative(n=60):
    """Jev assigns 0.8 to winners and 0.2 to losers, with a few honest misses."""
    trades = []
    for i in range(n):
        hit = i % 2 == 0
        p = 0.8 if hit else 0.2
        if i % 10 == 0:
            p = 0.2  # a confident miss on a winner
        trades.append(trade(p, hit, 1.5 if hit else -1.0))
    return trades


class MetricTests(unittest.TestCase):
    def test_brier_and_auc_hand_computed(self):
        self.assertAlmostEqual(brier([0.8, 0.2], [1, 0]), 0.04)
        self.assertEqual(auc([0.9, 0.8, 0.3, 0.1], [1, 1, 0, 0]), 1.0)
        self.assertEqual(auc([0.5, 0.5], [1, 0]), 0.5)
        self.assertAlmostEqual(auc([0.9, 0.2, 0.4, 0.1], [1, 1, 0, 0]), 0.75)
        self.assertIsNone(auc([0.5], [1]))

    def test_reliability_buckets(self):
        rows = reliability([0.1, 0.15, 0.9, 1.0], [0, 1, 1, 1])
        self.assertEqual([row["count"] for row in rows], [2, 0, 0, 0, 2])
        self.assertEqual(rows[0]["observed_rate"], 0.5)
        self.assertEqual(rows[4]["mean_probability"], 0.95)


class StatusTests(unittest.TestCase):
    def test_informative_jev_is_proven(self):
        report = evaluate_jev(informative())
        self.assertEqual(report["status"], "PROVEN", report["reasons"])
        self.assertEqual(report["base_rates"], {"BREAKOUT_52W": 0.5})
        self.assertGreater(report["brier_skill"], 0)
        self.assertGreater(report["filtered"]["expectancy_r"], report["unfiltered"]["expectancy_r"])

    def test_each_rule_can_fail_alone(self):
        constant = [dict(t, jev_p=0.5) for t in informative()]
        self.assertIn("Brier skill vs setup base rates is not positive", evaluate_jev(constant)["reasons"])
        few = informative()[:MIN_JUDGED_TRADES - 10]
        self.assertTrue(any(r.startswith("Only") for r in evaluate_jev(few)["reasons"]))
        inverted = [dict(t, jev_p=1 - t["jev_p"]) for t in informative()]
        reasons = evaluate_jev(inverted)["reasons"]
        self.assertIn("AUC not above 0.55", reasons)
        self.assertIn("Filtering on these probabilities does not raise expectancy", reasons)

    def test_unjudged_trades_are_excluded_and_counted(self):
        trades = informative() + [trade(None, True, 2.0)]
        report = evaluate_jev(trades)
        self.assertEqual((report["judged_trades"], report["unjudged_trades"]), (60, 1))
        self.assertEqual(evaluate_jev([trade(None, True, 1.0)])["status"], "UNPROVEN")

    def test_base_rates_are_per_setup(self):
        trades = informative() + [trade(0.9, True, 2.0, setup="LONG_BUILDUP") for _ in range(4)]
        report = evaluate_jev(trades)
        self.assertEqual(report["base_rates"]["LONG_BUILDUP"], 1.0)
        self.assertIn("LONG_BUILDUP", report["by_setup"])


if __name__ == "__main__":
    unittest.main()
