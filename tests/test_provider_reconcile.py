import json
from datetime import date, datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_fixtures as fx
from test_upstox_provider import EQUITY, INDEX, START, END, client, payload

from stockex.market.health import market_health
from stockex.market.importers import import_market_file
from stockex.market.schema import open_market_db
from stockex.providers.reconcile import reconcile_provider
from stockex.providers.upstox import ProviderError, sync_upstox


VERIFIED = datetime(2026, 9, 23, 11, tzinfo=timezone.utc)
URL = "https://nsearchives.nseindia.com/products/content/"


class ProviderReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = open_market_db(self.root / "target.sqlite3")
        self.addCleanup(self.target.close)
        self.reference_path = self.root / "reference.sqlite3"
        self.reference = open_market_db(self.reference_path)
        self.addCleanup(self.reference.close)
        self.manifest = {"schema_version": 1, "instruments": [EQUITY, INDEX]}
        sync_upstox(self.target, self.manifest, START, END, self.root / "raw",
                    client=client((200, payload(), {}), (200, payload(), {})))
        self.equity_path = self.root / "exchange-equity.csv"
        fx.write_udiff(self.equity_path, [fx.udiff_line(date.fromisoformat(START), "CM", "STK", "EXAMPLE",
            series="EQ", o=100, h=105, l=99, c=103, volume=50000, isin=EQUITY["isin"])])
        import_market_file(self.reference, self.equity_path)
        self.index_path = self.root / "exchange-index.csv"
        fx.write_index(self.index_path, [fx.index_line("Nifty 50", date.fromisoformat(START), 100, 105, 99, 103)])
        import_market_file(self.reference, self.index_path)

    def reconcile(self):
        return reconcile_provider(self.target, self.reference_path, URL, clock=lambda: VERIFIED)

    def codes(self, cutoff="2026-09-23T12:00:00Z"):
        return {item["code"] for item in market_health(self.target, START, min_history=1, known_at=cutoff)["issues"]}

    def test_exact_retained_raw_match_clears_only_current_knowledge_gate(self):
        self.assertIn("PROVIDER_PRICE_BASIS_UNVERIFIED", self.codes())
        result = self.reconcile()
        self.assertEqual((result["status"], result["new_receipts"]), ("MATCHED", 2))
        self.assertNotIn("PROVIDER_PRICE_BASIS_UNVERIFIED", self.codes())
        self.assertIn("PROVIDER_PRICE_BASIS_UNVERIFIED", self.codes("2026-09-23T10:00:00Z"))
        self.assertIn("not certified", result["assurance"])

    def test_identical_reconciliation_preserves_first_receipt(self):
        self.reconcile()
        result = self.reconcile()
        self.assertEqual(result["new_receipts"], 0)
        self.assertEqual(self.target.execute("SELECT COUNT(*) FROM provider_reconciliations").fetchone()[0], 2)

    def test_one_mismatched_instrument_cannot_issue_partial_receipts(self):
        self.reference.execute("UPDATE index_bars SET close=104")
        self.reference.commit()
        with self.assertRaises(ProviderError) as caught:
            self.reconcile()
        self.assertEqual(caught.exception.code, "PROVIDER_RECONCILIATION_FAILED")
        self.assertIsNone(self.target.execute("SELECT 1 FROM sqlite_master WHERE name='provider_reconciliations'").fetchone())
        self.assertIn("PROVIDER_PRICE_BASIS_UNVERIFIED", self.codes())

    def test_source_bytes_must_match_retained_import_hashes(self):
        self.equity_path.write_text("changed original source")
        with self.assertRaises(ProviderError) as caught:
            self.reconcile()
        self.assertEqual(caught.exception.code, "REFERENCE_SOURCE_UNAVAILABLE")

    def test_reference_database_cannot_override_disagreeing_retained_raw_bytes(self):
        import hashlib
        fx.write_index(self.index_path, [fx.index_line("Nifty 50", date.fromisoformat(START), 100, 105, 99, 104)])
        self.reference.execute("UPDATE market_imports SET sha256=? WHERE kind='index'",
                               (hashlib.sha256(self.index_path.read_bytes()).hexdigest(),))
        self.reference.commit()
        # The old DB still says 103, matching the provider. The actual retained
        # reference bytes say 104, so matching the DB alone must not pass.
        with self.assertRaises(ProviderError) as caught:
            self.reconcile()
        self.assertEqual(caught.exception.code, "PROVIDER_RECONCILIATION_FAILED")

    def test_target_rows_must_match_the_audited_download_and_reference(self):
        self.target.execute("UPDATE bars SET close=104")
        self.target.commit()
        with self.assertRaises(ProviderError) as caught:
            self.reconcile()
        self.assertEqual(caught.exception.code, "PROVIDER_RECONCILIATION_FAILED")

    def test_changing_source_bytes_between_hashing_and_replay_cannot_clear_gate(self):
        import hashlib
        import stockex.providers.reconcile as module
        fx.write_index(self.index_path, [fx.index_line("Nifty 50", date.fromisoformat(START), 100, 105, 99, 104)])
        self.reference.execute("UPDATE market_imports SET sha256=? WHERE kind='index'",
                               (hashlib.sha256(self.index_path.read_bytes()).hexdigest(),))
        self.reference.commit()
        original = module.import_market_file
        def replace_during_replay(connection, path, **kwargs):
            if Path(path) == self.index_path:
                fx.write_index(self.index_path, [fx.index_line("Nifty 50", date.fromisoformat(START), 100, 105, 99, 103)])
            return original(connection, path, **kwargs)
        with patch.object(module, "import_market_file", side_effect=replace_during_replay):
            with self.assertRaises(ProviderError) as caught:
                self.reconcile()
        self.assertEqual(caught.exception.code, "REFERENCE_SOURCE_CHANGED")
        self.assertIn("PROVIDER_PRICE_BASIS_UNVERIFIED", self.codes())

    def test_provider_cannot_be_its_own_raw_reference(self):
        with self.assertRaisesRegex(ValueError, "not provider"):
            reconcile_provider(self.target, self.root / "target.sqlite3", URL, clock=lambda: VERIFIED)

    def test_source_identity_and_series_must_match(self):
        self.reference.execute("UPDATE bars SET series='BE'")
        self.reference.commit()
        with self.assertRaises(ProviderError):
            self.reconcile()

    def test_retained_mapping_hash_must_remain_intact(self):
        self.target.execute("UPDATE provider_manifests SET manifest_json='{}'")
        with self.assertRaises(ProviderError) as caught:
            self.reconcile()
        self.assertEqual(caught.exception.code, "PROVIDER_MAPPING_UNAVAILABLE")

    def test_reference_url_cannot_carry_credentials_or_arbitrary_host(self):
        for url in ("https://user:secret@nseindia.com/", "http://nseindia.com/", "https://attacker.example/", URL + "?token=secret"):
            with self.assertRaises(ValueError):
                reconcile_provider(self.target, self.reference_path, url, clock=lambda: VERIFIED)
