import copy
import pathlib
import random
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.backtest import build_scorecard, data_fingerprint, run_backtest
from stockex.jev.calibration import auc
from stockex.market.importers import import_market_file
from stockex.market.queries import trading_dates
from stockex.market.schema import open_market_db
from stockex.signals.meta_model import MODEL_FEATURE_VERSION, LogisticModel, WalkForwardModel
from stockex.signals.scan import model_proof, scan
from stockex.signals.setups import SETUPS


class LogisticTests(unittest.TestCase):
    def test_learns_a_signal_and_round_trips(self):
        rng = random.Random(1)
        rows, labels = [], []
        for _ in range(300):
            x = rng.uniform(-1, 1)
            rows.append({"x": x, "noise": rng.uniform(-1, 1)})
            labels.append(1 if x + rng.gauss(0, 0.3) > 0 else 0)
        model = LogisticModel.fit(rows, labels)
        self.assertGreater(model.predict({"x": 0.8, "noise": 0}), 0.8)
        self.assertLess(model.predict({"x": -0.8, "noise": 0}), 0.2)
        self.assertGreater(auc([model.predict(r) for r in rows], labels), 0.85)
        clone = LogisticModel.from_dict(model.to_dict())
        self.assertEqual(clone.predict(rows[0]), model.predict(rows[0]))
        self.assertEqual(model.to_dict()["feature_version"], MODEL_FEATURE_VERSION)

    def test_walk_forward_only_uses_closed_trades(self):
        wf = WalkForwardModel(["A"], min_train=4, refit_every=1)
        trades = [{"exit_date": f"2026-01-0{i}", "t1_hit": i % 2 == 0, "model_features": {"x": float(i % 2)}}
                  for i in range(1, 9)]
        wf.maybe_refit("2026-01-03", trades)
        self.assertIsNone(wf.model)  # only two trades had closed before the 3rd
        wf.maybe_refit("2026-01-09", trades)
        self.assertEqual(wf.model.trained_on, 8)


class ModelScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.directory.name)
        cls.db = open_market_db(root / "m.sqlite3")
        for path in fx.generate_market(root, symbols=40, days=300, fo_symbols=10, seed=21):
            import_market_file(cls.db, path)
        cls.dates = trading_dates(cls.db, "2000-01-01", "2100-01-01")
        cls.result = run_backtest(cls.db, cls.dates[200], cls.dates[-15])
        cls.card = build_scorecard(cls.result, data_fingerprint(cls.db, cls.dates[200], cls.dates[-15]))
        cls.day = next(d for d in reversed(cls.dates[200:]) if len(scan(cls.db, d)["candidates"]) >= 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.directory.cleanup()

    def test_backtest_reports_out_of_sample_model(self):
        model = self.result["model"]
        self.assertGreaterEqual(model["walk_forward_fits"], 1)
        self.assertGreater(model["judged_trades"], 0)
        self.assertLess(model["judged_trades"], self.result["overall"]["trades"])  # early trades have no model yet
        self.assertIsNotNone(model["coefficients"])
        self.assertNotIn("model_features", self.result["trades"][0])
        self.assertEqual(self.card["model"]["status"], model["status"])

    def test_unproven_model_is_information_only(self):
        card = copy.deepcopy(self.card)
        card["model"]["status"] = "UNPROVEN"
        plain = scan(self.db, self.day)
        report = scan(self.db, self.day, scorecard=card)
        self.assertEqual([c["symbol"] for c in report["candidates"]], [c["symbol"] for c in plain["candidates"]])
        self.assertTrue(all(c["model"]["effect"] == "NONE" for c in report["candidates"]))
        self.assertTrue(any(note.startswith("Model shown for information only") for note in report["notes"]))

    def test_proven_model_filters_and_ranks(self):
        card = copy.deepcopy(self.card)
        card["model"].update(status="PROVEN", brier_skill=0.05, auc=0.6,
                             base_rates={name: 0.5 for name in SETUPS})
        report = scan(self.db, self.day, top=50, scorecard=card)
        plain = scan(self.db, self.day, top=50)
        filtered = [r for r in report["rejected"] if r["code"] == "MODEL_FILTERED"]
        self.assertEqual(len(filtered) + len(report["candidates"]), len(plain["candidates"]))
        for candidate in report["candidates"]:
            self.assertGreaterEqual(candidate["model"]["follow_through"], 0.5)
            self.assertIn("model_edge", candidate["score"]["components"])
        self.assertTrue(any(note.startswith("Model is PROVEN") for note in report["notes"]))

    def test_more_skilful_proven_judge_wins(self):
        class Jev:
            model = "jev-test"

            def evaluate(self, state, questions):
                return {"model": "jev-1", "answers": {
                    "follow_through": {"type": "noul", "noul": 0.99},
                    "catalyst_quality": {"type": "score", "score": "weak", "confidence": 0.6},
                    "crowding_risk": {"type": "noul", "noul": 0.2},
                    "failure_mode": {"type": "choice", "choice": "none_obvious", "confidence": 0.5}}}

        card = copy.deepcopy(self.card)
        rates = {name: 0.5 for name in SETUPS}
        card["model"].update(status="PROVEN", brier_skill=0.02, auc=0.6, base_rates=rates)
        card["jev"] = {"status": "PROVEN", "question_bank_version": "1", "model_requested": "jev-test",
                       "brier_skill": 0.08, "auc": 0.65, "base_rates": rates}
        report = scan(self.db, self.day, scorecard=card, jev_client=Jev())
        self.assertEqual(report["meta"]["chosen"], "JEV")
        self.assertTrue(all(c["jev"]["effect"] == "RANKED" and c["model"]["effect"] == "NONE"
                            for c in report["candidates"]))

    def test_model_proof_rules(self):
        self.assertEqual(model_proof(None)["status"], "NO_SCORECARD")
        card = copy.deepcopy(self.card)
        card["model"]["feature_version"] = "0"
        self.assertEqual(model_proof(card)["status"], "UNPROVEN")


if __name__ == "__main__":
    unittest.main()
