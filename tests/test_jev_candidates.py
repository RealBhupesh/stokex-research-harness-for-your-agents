import json
import sqlite3
import unittest

from stockex.jev.cache import JevCache
from stockex.jev.candidates import (
    CANDIDATE_QUESTIONS, JudgeBudget, candidate_state, judge_state,
)
from stockex.jev.client import JevRequestError, validate_questions


CANDIDATE = {
    "symbol": "RELIANCE", "date": "2026-09-22", "setup": "DEAL_FOLLOW_THROUGH", "other_setups": ["BREAKOUT_52W"],
    "close": 2900.0,
    "plan": {"entry": 2905.0, "stop": 2850.0, "t1": 2987.5, "t2": 3070.0,
             "reward_risk_after_costs": 2.7, "time_stop_sessions": 7},
    "evidence": {"deal_kind": "BLOCK", "client": "BIG FUND LTD", "deal_date": "2026-09-22",
                 "deal_price": 2880.0, "deal_value": 9e8, "deal_vs_median_daily_value": 1.4},
    "fo": {"quadrant": "LONG_BUILDUP", "oi_chg1": 0.08, "oi_chg5": 0.12, "rollover": 0.3, "days_to_expiry": 6},
    "catalyst": {"type": "BLOCK_DEAL", "date": "2026-09-22", "source": "NSE", "verified": True},
    "liquidity": {"median_traded_value_20d": 1.2e10, "atr_pct": 0.02},
}
ROW = {"ret1": 0.021, "ret5": 0.04, "ret20": 0.08, "ret60": 0.15, "rs20": 0.05, "rs60": 0.09, "vol_ratio": 2.4,
       "deliv_ratio": 1.3, "atr_pct": 0.02, "close_position": 0.85, "gap_pct": 0.004, "base_range20": 0.07,
       "atr_contraction": 0.75, "sma20": 2800.0, "sma50": 2700.0, "sma200": 2500.0, "high252": 2950.0}
REGIME = {"label": "RISK_ON", "inputs": {"nifty_close": 25010.5, "nifty_ret20": 0.03, "breadth_above_sma50": 0.62,
                                         "vix": 12.4, "vix_chg5": -0.05}}
ANSWERS = {
    "follow_through": {"type": "noul", "noul": 0.64},
    "catalyst_quality": {"type": "score", "score": "strong", "confidence": 0.8},
    "crowding_risk": {"type": "noul", "noul": 0.2},
    "failure_mode": {"type": "choice", "choice": "market_drag", "confidence": 0.6},
}


class FakeClient:
    model = "jev-test"

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def evaluate(self, state, questions):
        self.calls += 1
        if self.fail:
            raise JevRequestError("JEV_HTTP_ERROR", "Jev returned HTTP 503")
        return {"model": "jev-1.13.0", "answers": ANSWERS}


class CandidateStateTests(unittest.TestCase):
    def test_state_is_anonymized(self):
        text = json.dumps(candidate_state(CANDIDATE, ROW, REGIME))
        for secret in ("RELIANCE", "2026", "BIG FUND", "2900", "2905", "25010", "9000000"):
            self.assertNotIn(secret, text)

    def test_state_keeps_relative_levels_and_context(self):
        state = candidate_state(CANDIDATE, ROW, REGIME)
        self.assertAlmostEqual(state["plan"]["stop_pct"], round(2850 / 2900 - 1, 4))
        self.assertAlmostEqual(state["evidence"]["deal_price"], round(2880 / 2900 - 1, 4))
        self.assertNotIn("deal_kind", state["evidence"])  # text evidence is dropped; catalyst type carries it
        self.assertEqual(state["catalyst"], {"type": "BLOCK_DEAL", "verified": True})
        self.assertEqual(state["liquidity"], "over_200_crore")
        self.assertEqual(state["market"]["regime"], "RISK_ON")
        self.assertAlmostEqual(state["technicals"]["vs_52w_high"], round(2900 / 2950 - 1, 4))
        self.assertEqual(state, candidate_state(CANDIDATE, ROW, REGIME))

    def test_question_bank_is_valid(self):
        validate_questions(CANDIDATE_QUESTIONS)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.cache = JevCache(self.connection)
        self.state = candidate_state(CANDIDATE, ROW, REGIME)

    def test_judgment_summary_and_cache(self):
        client = FakeClient()
        first = judge_state(self.state, client, self.cache)
        second = judge_state(self.state, client, self.cache)
        self.assertEqual(client.calls, 1)
        self.assertEqual((first["follow_through"], first["catalyst_quality"], first["failure_mode"]),
                         (0.64, "strong", "market_drag"))
        self.assertEqual((first["cached"], second["cached"], second["model"]), (False, True, "jev-1.13.0"))

    def test_cache_is_keyed_by_model(self):
        judge_state(self.state, FakeClient(), self.cache)
        other = FakeClient()
        other.model = "jev-other"
        judge_state(self.state, other, self.cache)
        self.assertEqual(other.calls, 1)

    def test_budget_and_errors_become_gaps(self):
        budget = JudgeBudget(0)
        gap = judge_state(self.state, FakeClient(), self.cache, budget)
        self.assertEqual((gap["status"], budget.report()["skipped_budget"]), ("JEV_UNAVAILABLE", 1))
        budget = JudgeBudget(5)
        failed = judge_state(self.state, FakeClient(fail=True), self.cache, budget)
        self.assertEqual((failed["status"], budget.errors), ("JEV_UNAVAILABLE", 1))
        self.assertIsNone(self.cache.get(failed["input_sha256"], "1", "jev-test"))


if __name__ == "__main__":
    unittest.main()
