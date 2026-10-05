import copy
import itertools
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.backtest import build_scorecard, data_fingerprint, run_backtest
from stockex.jev.cache import JevCache
from stockex.jev.candidates import CANDIDATE_QUESTION_BANK_VERSION
from stockex.market.importers import import_market_file
from stockex.market.queries import trading_dates
from stockex.market.schema import open_market_db
from stockex.signals.scan import jev_proof, scan
from stockex.signals.setups import SETUPS


def answers(p):
    return {
        "follow_through": {"type": "noul", "noul": p},
        "catalyst_quality": {"type": "score", "score": "moderate", "confidence": 0.7},
        "crowding_risk": {"type": "noul", "noul": 0.3},
        "failure_mode": {"type": "choice", "choice": "none_obvious", "confidence": 0.5},
    }


class FeatureClient:
    """Fake Jev whose probability depends only on anonymized features."""
    model = "jev-test"

    def __init__(self):
        self.calls = 0
        self.states = []

    def evaluate(self, state, questions):
        self.calls += 1
        self.states.append(state)
        rs = state["technicals"].get("rs20") or 0
        return {"model": "jev-1.13.0", "answers": answers(max(0.05, min(0.95, 0.5 + 2 * rs)))}


class SequenceClient:
    model = "jev-test"

    def __init__(self, values):
        self.values = itertools.cycle(values)

    def evaluate(self, state, questions):
        return {"model": "jev-1.13.0", "answers": answers(next(self.values))}


def proven_scorecard(base_rate=0.5):
    return {"jev": {"status": "PROVEN", "question_bank_version": CANDIDATE_QUESTION_BANK_VERSION,
                    "model_requested": "jev-test", "brier_skill": 0.1, "auc": 0.62,
                    "base_rates": {name: base_rate for name in SETUPS}}}


class JevModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.directory.name)
        cls.db = open_market_db(root / "m.sqlite3")
        for path in fx.generate_market(root, symbols=40, days=300, fo_symbols=10, seed=21):
            import_market_file(cls.db, path)
        cls.dates = trading_dates(cls.db, "2000-01-01", "2100-01-01")
        cls.scan_day = next(day for day in reversed(cls.dates[200:])
                            if len(scan(cls.db, day)["candidates"]) >= 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.directory.cleanup()

    def test_backtest_reports_calibration_and_caches_judgments(self):
        start, end = self.dates[200], self.dates[-15]
        cache = JevCache(self.db)
        client = FeatureClient()
        result = run_backtest(self.db, start, end, jev_client=client, jev_cache=cache)
        jev = result["jev"]
        self.assertEqual(jev["judged_trades"], result["overall"]["trades"])
        self.assertEqual(jev["usage"]["calls"], client.calls)
        self.assertIn(jev["status"], {"PROVEN", "UNPROVEN"})
        self.assertEqual(jev["models_returned"], ["jev-1.13.0"])
        self.assertTrue(all("t1_hit" in t and t["jev_p"] is not None for t in result["trades"]))
        for state in client.states:
            text = repr(state)
            self.assertFalse(any(day in text for day in self.dates))
            self.assertNotIn("SYM", text)

        again = FeatureClient()
        repeat = run_backtest(self.db, start, end, jev_client=again, jev_cache=cache)
        self.assertEqual((again.calls, repeat["jev"]["usage"]["cached"]), (0, client.calls))
        self.assertEqual(repeat["jev"]["brier"], jev["brier"])

        card = build_scorecard(result, data_fingerprint(self.db, start, end))
        self.assertEqual(card["jev"]["model_requested"], "jev-test")
        self.assertNotIn("usage", card["jev"])

    def test_constant_jev_is_unproven_and_budget_is_respected(self):
        start, end = self.dates[200], self.dates[-15]
        result = run_backtest(self.db, start, end, jev_client=SequenceClient([0.5]), jev_max_calls=5)
        self.assertEqual(result["jev"]["status"], "UNPROVEN")
        self.assertEqual(result["jev"]["usage"]["calls"], 5)
        self.assertEqual(result["jev"]["judged_trades"], 5)
        self.assertTrue(any(t["jev"]["status"] == "JEV_UNAVAILABLE" for t in result["trades"]))

    def test_unproven_jev_never_changes_the_scan(self):
        plain = scan(self.db, self.scan_day)
        unproven = copy.deepcopy(proven_scorecard())
        unproven["jev"]["status"] = "UNPROVEN"
        for card in (None, unproven):
            with self.subTest(card=bool(card)):
                judged = scan(self.db, self.scan_day, scorecard=card, jev_client=SequenceClient([0.9, 0.1]))
                self.assertEqual([c["symbol"] for c in judged["candidates"]], [c["symbol"] for c in plain["candidates"]])
                self.assertTrue(all(c["jev"]["effect"] == "NONE" for c in judged["candidates"]))
                self.assertTrue(any("information only" in note for note in judged["notes"]))

    def test_proven_jev_filters_and_reranks(self):
        plain = scan(self.db, self.scan_day, top=50)
        judged = scan(self.db, self.scan_day, top=50, scorecard=proven_scorecard(),
                      jev_client=SequenceClient([0.9, 0.1]))
        filtered = [r for r in judged["rejected"] if r["code"] == "JEV_FILTERED"]
        self.assertEqual(len(filtered) + len(judged["candidates"]), len(plain["candidates"]))
        self.assertEqual(len(filtered), len(plain["candidates"]) // 2)
        self.assertTrue(all(c["jev"]["effect"] == "RANKED" for c in judged["candidates"]))
        self.assertTrue(all("jev_edge" in c["score"]["components"] for c in judged["candidates"]))
        self.assertEqual([c["rank"] for c in judged["candidates"]], list(range(1, len(judged["candidates"]) + 1)))

    def test_proof_requires_matching_bank_and_model(self):
        client = SequenceClient([0.5])
        self.assertEqual(jev_proof(proven_scorecard(), client)["status"], "PROVEN")
        other = proven_scorecard()
        other["jev"]["model_requested"] = "jev-other"
        self.assertEqual(jev_proof(other, client)["status"], "UNPROVEN")
        other = proven_scorecard()
        other["jev"]["question_bank_version"] = "0"
        self.assertEqual(jev_proof(other, client)["status"], "UNPROVEN")
        self.assertEqual(jev_proof({}, client)["status"], "NO_SCORECARD")


if __name__ == "__main__":
    unittest.main()
