"""Regression tests for failures that can silently contaminate research."""

import contextlib
import io
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_fixtures as fx

from stockex.cli import main
from stockex.market.health import market_health
from stockex.market.importers import MarketImportError, import_market_batch, import_market_file
from stockex.market.queries import option_chain, sector_maps_by_day
from stockex.market.schema import open_market_db
from stockex.operations import atomic_json, backup_database
from stockex.signals.scan import _track_record, scan
from stockex.signals.setups import SETUP_VERSIONS
from stockex.store.database import PointInTimeStore


class ProductionControlsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.path = self.root / "market.sqlite3"
        self.db = open_market_db(self.path)
        self.day = date(2026, 9, 21)

    def tearDown(self):
        self.db.close()
        self.temporary.cleanup()

    def cash_file(self, name="cash.csv", close=104):
        path = self.root / name
        fx.write_cm_full(path, [fx.cm_full_line("ABC", self.day, 100, 105, 99, close, 100, 50000)])
        return path

    def test_batch_failure_rolls_back_data_and_both_import_ledgers(self):
        good = self.cash_file()
        bad = self.root / "bad.csv"
        bad.write_text("symbol,series,date1,closeprice\nABC,EQ,invalid,100\n")
        with self.assertRaises(MarketImportError):
            import_market_batch(self.db, [good, bad])
        for table in ("bars", "market_imports", "market_import_runs"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)

    def test_import_does_not_commit_callers_transaction(self):
        self.db.execute("BEGIN")
        import_market_file(self.db, self.cash_file())
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 0)

    def test_changed_option_retention_is_not_false_duplicate(self):
        path = self.root / "options.csv"
        fx.write_udiff(path, [fx.udiff_line(self.day, "FO", "STO", "ABC", expiry=date(2026, 9, 29),
                                          strike=100, option="CE", c=5, oi=100, volume=1)])
        import_market_file(self.db, path, option_expiries=0)
        result = import_market_file(self.db, path, option_expiries=None)
        self.assertEqual((result["status"], result["written"]), ("imported", 1))
        self.assertEqual(import_market_file(self.db, path, option_expiries=None)["status"], "unchanged")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM market_import_runs").fetchone()[0], 2)

    def test_changing_content_availability_is_rejected(self):
        path = self.cash_file()
        import_market_file(self.db, path)
        with self.assertRaises(MarketImportError) as caught:
            import_market_file(self.db, path, available_at="2026-09-22T13:00:00Z")
        self.assertEqual(caught.exception.code, "IMPORT_AVAILABILITY_CONFLICT")

    def test_conflicting_prices_do_not_silently_keep_first_source(self):
        import_market_file(self.db, self.cash_file())
        with self.assertRaises(MarketImportError) as caught:
            import_market_file(self.db, self.cash_file("revision.csv", close=103))
        self.assertEqual(caught.exception.code, "BAR_CONFLICT")
        self.assertEqual(self.db.execute("SELECT close FROM bars").fetchone()[0], 104)

    def test_options_do_not_leak_later_available_rows_at_same_expiry(self):
        for option, availability in (("CE", None), ("PE", "2026-09-22T13:00:00Z")):
            path = self.root / (option + ".csv")
            fx.write_udiff(path, [fx.udiff_line(self.day, "FO", "STO", "ABC", expiry=date(2026, 9, 29),
                                              strike=100, option=option, c=5, oi=100, volume=1)])
            import_market_file(self.db, path, available_at=availability)
        self.assertEqual([item["instrument"] for item in option_chain(self.db, "ABC", self.day.isoformat())],
                         ["CE"])

    def test_future_sector_snapshot_does_not_rewrite_history(self):
        self.db.executemany("INSERT INTO index_members VALUES ('NIFTY500', 'ABC', ?, NULL, ?)",
                            [("Banks", "2026-09-21"), ("Technology", "2026-09-23")])
        maps = sector_maps_by_day(self.db, ["2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23"])
        self.assertEqual(maps["2026-09-20"], {})
        self.assertEqual(maps["2026-09-21"], {"ABC": "Banks"})
        self.assertEqual(maps["2026-09-22"], {"ABC": "Banks"})
        self.assertEqual(maps["2026-09-23"], {"ABC": "Technology"})

    def test_overlapping_scorecard_rejected_before_loading_or_judging(self):
        for period in ({"to": "2026-09-21", "data_through": "2026-09-21"},
                       {"to": "2026-09-01", "data_through": "2026-09-22"}, {}):
            with patch.object(importlib.import_module("stockex.signals.scan"), "prepare_universe") as prepare:
                with self.assertRaises(ValueError):
                    scan(self.db, "2026-09-21", scorecard={"period": period})
                prepare.assert_not_called()

    def test_positive_expectancy_alone_cannot_become_proven(self):
        setup = next(iter(SETUP_VERSIONS))
        card = {"setups": {setup: {"version": SETUP_VERSIONS[setup],
                                  "overall": {"trades": 100, "expectancy_r": 0.2}}}}
        self.assertEqual(_track_record(card, setup, "NORMAL")["status"], "UNPROVEN")

    def test_health_blocks_missing_and_insufficient_session(self):
        import_market_file(self.db, self.cash_file())
        report = market_health(self.db, "2026-09-22")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("SESSION_MISSING", {issue["code"] for issue in report["issues"]})
        self.assertEqual(market_health(self.db, "2026-09-21")["status"], "BLOCKED")

    def test_health_detects_impossible_ohlc(self):
        import_market_file(self.db, self.cash_file())
        self.db.execute("UPDATE bars SET open = high + 1")
        report = market_health(self.db, "2026-09-21", min_history=1)
        self.assertIn("INVALID_BARS", {issue["code"] for issue in report["issues"]})

    def test_health_passes_covered_session_with_explicit_requirements(self):
        import_market_file(self.db, self.cash_file())
        path = self.root / "index.csv"
        fx.write_index(path, [fx.index_line("Nifty 50", self.day, 25000, 25100, 24900, 25050)])
        import_market_file(self.db, path)
        report = market_health(self.db, self.day.isoformat(), min_history=1)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(any(issue["severity"] == "BLOCK" for issue in report["issues"]))

    def test_strict_scan_returns_nonzero_and_never_journals_missing_session(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main(["scan", str(self.path), "--as-of", "2026-09-21", "--strict-data", "--journal"])
        self.assertEqual(result, 3)
        self.assertEqual(json.loads(stdout.getvalue())["candidates"], [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM journal").fetchone()[0], 0)

    def test_cli_rejects_nonfinite_sizing(self):
        for value in ("nan", "inf", "0"):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["scan", str(self.path), "--as-of", "2026-09-21",
                                       "--capital", value]), 2)

    def test_verified_backup_can_be_reopened_and_never_overwrites(self):
        import_market_file(self.db, self.cash_file())
        destination = self.root / "backup.sqlite3"
        report = backup_database(self.path, destination)
        with sqlite3.connect(destination) as restored:
            self.assertEqual(restored.execute("SELECT close FROM bars").fetchone()[0], 104)
        self.assertEqual(len(report["sha256"]), 64)
        with self.assertRaises(FileExistsError):
            backup_database(self.path, destination)

    def test_failed_report_replace_preserves_previous_file(self):
        path = self.root / "report.json"
        path.write_text('{"old": true}')
        with patch("stockex.operations.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                atomic_json(path, {"new": True})
        self.assertEqual(json.loads(path.read_text()), {"old": True})
        self.assertEqual(list(self.root.glob(".stockex-*")), [])

    def test_store_types_cannot_be_mixed(self):
        with self.assertRaises(sqlite3.DatabaseError):
            PointInTimeStore.open(self.path)
        evidence = self.root / "evidence.sqlite3"
        with PointInTimeStore.open(evidence):
            pass
        with self.assertRaises(sqlite3.DatabaseError):
            open_market_db(evidence)

    def test_future_market_schema_rejected_without_adding_tables(self):
        path = self.root / "future.sqlite3"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE market_schema_version(version INTEGER, applied_at TEXT)")
            connection.execute("INSERT INTO market_schema_version VALUES (999, '')")
        with self.assertRaises(sqlite3.DatabaseError):
            open_market_db(path)
        with sqlite3.connect(path) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                             [("market_schema_version",)])
