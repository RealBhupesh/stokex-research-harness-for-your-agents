"""Immutable, cutoff-aware interpretation of primary exchange announcements."""

from datetime import datetime, timezone
import json
import sqlite3
import unittest

from stockex.backtest.scorecard import data_fingerprint
from stockex.jev.announcements import (
    ANNOUNCEMENT_QUESTION_BANK_VERSION,
    announcement_hash, classify_with_jev,
)
from stockex.jev.client import JevResponseError
from stockex.market.queries import announcements_between
from stockex.market.schema import initialize_market_schema, open_market_db
from stockex.signals.scan import _announcement_catalysts


BROADCAST = "2026-09-22T05:00:00Z"
JUDGED = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)


class Client:
    model = "jev-pinned-request"

    def __init__(self, category="ORDER_WIN", confidence=0.9, callback=None):
        self.calls = 0
        self.category, self.confidence, self.callback = category, confidence, callback

    def evaluate(self, state, questions):
        self.calls += 1
        if self.callback:
            self.callback()
        return {"model": "jev-returned-version", "answers": {
            "category": {"type": "choice", "choice": self.category, "confidence": self.confidence,
                         "probabilities": {key: float(key == self.category)
                                           for key in questions["category"]["criteria"]}},
            "material": {"type": "noul", "noul": 0.7},
        }}


class AnnouncementProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = open_market_db(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("INSERT INTO announcements VALUES (?,?,?,?,?,?)",
                        ("ABC", BROADCAST, "Updates", "An important order", "OTHER", "KEYWORD"))
        self.db.commit()

    def classify(self, client=None, **kwargs):
        return classify_with_jev(self.db, client or Client(), clock=lambda: JUDGED, **kwargs)

    def query(self, end="2026-09-22", **kwargs):
        return announcements_between(self.db, "2026-09-22", end, **kwargs)["ABC"][0]

    def test_raw_evidence_stays_unchanged_and_annotation_has_complete_provenance(self):
        before = tuple(self.db.execute("SELECT * FROM announcements").fetchone())
        self.assertEqual(self.classify()["reclassified"], 1)
        self.assertEqual(tuple(self.db.execute("SELECT * FROM announcements").fetchone()), before)
        row = self.db.execute("SELECT * FROM announcement_classifications").fetchone()
        self.assertEqual((row["model_requested"], row["model_returned"]),
                         ("jev-pinned-request", "jev-returned-version"))
        self.assertEqual(row["question_bank_version"], ANNOUNCEMENT_QUESTION_BANK_VERSION)
        self.assertEqual(row["input_sha256"], announcement_hash("Updates", "An important order"))
        self.assertEqual(row["judged_at"], "2026-09-23T08:00:00Z")
        self.assertEqual(json.loads(row["response_json"])["answers"]["material"]["noul"], 0.7)

    def test_judgment_does_not_change_historical_cutoffs_and_explicit_later_cutoff_works(self):
        self.classify()
        self.assertEqual(self.query()["category"], "OTHER")
        self.assertEqual(self.query(known_at="2026-09-23T07:59:59Z")["category"], "OTHER")
        row = self.query(known_at="2026-09-23T08:00:00Z")
        self.assertEqual((row["category"], row["category_source"]), ("ORDER_WIN", "JEV_INTERPRETATION"))
        self.assertEqual((row["raw_category"], row["raw_category_source"]), ("OTHER", "KEYWORD"))
        self.assertEqual(self.query(end="2026-09-23")["category"], "ORDER_WIN")

    def test_model_annotation_is_idempotent_and_preserves_first_judgment_time(self):
        client = Client()
        self.classify(client)
        self.assertEqual(self.classify(client)["examined"], 0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM announcement_classifications").fetchone()[0], 1)
        self.classify(client, min_confidence=0.95)
        self.assertEqual(client.calls, 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM announcement_classifications").fetchone()[0], 2)

    def test_equivalent_numeric_confidence_policies_share_cache_identity(self):
        client = Client()
        self.classify(client, min_confidence=1)
        self.assertEqual(self.classify(client, min_confidence=1.0)["examined"], 0)
        self.assertEqual(client.calls, 1)

    def test_stricter_policy_wins_when_timestamp_precision_cannot_order_annotations(self):
        self.classify(min_confidence=0.95)
        self.classify(min_confidence=0.6)
        self.assertEqual(self.query(end="2026-09-23")["category"], "OTHER")

    def test_annotation_cannot_be_updated_or_deleted(self):
        self.classify()
        for sql in ("UPDATE announcement_classifications SET category='RESULTS'",
                    "DELETE FROM announcement_classifications"):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)

    def test_stale_annotation_does_not_apply_to_changed_input(self):
        self.classify()
        self.db.execute("UPDATE announcements SET details='Different disclosure'")
        self.db.commit()
        self.assertEqual(self.query(end="2026-09-23")["category"], "OTHER")

    def test_low_confidence_and_invalid_provider_responses_cannot_promote_evidence(self):
        self.classify(Client(confidence=0.3))
        self.assertEqual(self.query(end="2026-09-23")["category"], "OTHER")
        bad = Client(category="INVENTED")
        bad.model = "other-request"
        self.assertEqual(self.classify(bad)["errors"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM announcement_classifications").fetchone()[0], 1)

    def test_competing_result_for_same_identity_raises_immutable_conflict(self):
        # Simulate another worker publishing while the first worker awaits Jev.
        outer = Client(callback=lambda: self.classify(Client(category="RESULTS")))
        with self.assertRaises(JevResponseError) as caught:
            self.classify(outer)
        self.assertEqual(caught.exception.code, "JEV_CLASSIFICATION_CONFLICT")
        self.assertEqual(self.db.execute("SELECT category FROM announcement_classifications").fetchone()[0], "RESULTS")

    def test_fingerprint_changes_when_signal_interpretations_change(self):
        first = data_fingerprint(self.db, "2026-09-22", "2026-09-23")
        self.classify()
        self.assertNotEqual(first, data_fingerprint(self.db, "2026-09-22", "2026-09-23"))

    def test_catalyst_provenance_is_honest_and_cutoff_aware(self):
        self.classify()
        class Series:
            dates = ["2026-09-22", "2026-09-23"]
        class Features:
            series = Series()
        self.assertEqual(_announcement_catalysts(self.db, {"ABC": Features()}, "2026-09-22", "2026-09-22"), {})
        event = _announcement_catalysts(self.db, {"ABC": Features()}, "2026-09-22", "2026-09-23")["ABC"]["2026-09-22"]
        self.assertFalse(event["verified"])
        self.assertEqual(event["source"], "Jev interpretation of NSE announcement")
        self.assertEqual(event["classification"]["model_returned"], "jev-returned-version")

    def test_legacy_untimed_mutations_cannot_create_historical_catalysts(self):
        self.db.execute("UPDATE announcements SET category='RESULTS', category_source='JEV'")
        self.db.commit()
        row = self.query(end="2026-09-23")
        self.assertEqual((row["category"], row["category_source"]), ("OTHER", "JEV_LEGACY_UNTIMED"))
        self.classify()
        self.assertEqual(self.query()["category"], "OTHER")
        self.assertEqual(self.query(end="2026-09-23")["category"], "ORDER_WIN")

    def test_version_four_upgrade_preserves_raw_legacy_rows_and_adds_provenance(self):
        self.db.execute("UPDATE announcements SET category='RESULTS', category_source='JEV'")
        original = tuple(self.db.execute("SELECT * FROM announcements").fetchone())
        self.db.execute("DROP TABLE announcement_classifications")
        self.db.execute("DELETE FROM market_schema_version")
        self.db.execute("INSERT INTO market_schema_version VALUES (4, '2026-09-01T00:00:00Z')")
        self.db.commit()
        initialize_market_schema(self.db)
        self.assertEqual(tuple(self.db.execute("SELECT * FROM announcements").fetchone()), original)
        self.assertEqual(self.db.execute("SELECT MAX(version) FROM market_schema_version").fetchone()[0], 5)
        self.assertEqual(self.query()["category"], "OTHER")
        self.assertEqual(self.classify()["reclassified"], 1)

    def test_argument_validation_and_no_backdated_judgments(self):
        for kwargs in ({"min_confidence": 0}, {"min_confidence": float("nan")}, {"limit": -1}, {"limit": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.classify(**kwargs)
        with self.assertRaises(ValueError):
            classify_with_jev(self.db, Client(), clock=lambda: datetime(2026, 9, 21, tzinfo=timezone.utc))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM announcement_classifications").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
