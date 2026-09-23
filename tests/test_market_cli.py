import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.cli import main


class MarketCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls.directory.name)
        cls.database = cls.root / "market.sqlite3"
        cls.files = fx.generate_market(cls.root, symbols=20, days=260, fo_symbols=6, seed=3)
        code, payload, error = cls.call(["market-import", str(cls.database), *map(str, cls.files)])
        assert code == 0, error
        cls.imported = payload

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @staticmethod
    def call(argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        out = stdout.getvalue()
        try:
            payload = json.loads(out) if out else None
        except ValueError:
            payload = out
        return code, payload, json.loads(stderr.getvalue()) if stderr.getvalue() else None

    def last_date(self):
        return self.call(["market-status", str(self.database)])[1]["bars"]["last"]

    def test_import_summary_and_status(self):
        self.assertEqual(len(self.imported), len(self.files))
        self.assertEqual({item["kind"] for item in self.imported}, {"cm-full", "index", "udiff"})
        code, status, _ = self.call(["market-status", str(self.database)])
        self.assertEqual(code, 0)
        self.assertEqual((status["bars"]["symbols"], status["bars"]["dates"]), (20, 260))
        self.assertIn("NIFTY 50", status["index_bars"]["indices"])
        again = self.call(["market-import", str(self.database), str(self.files[0])])[1]
        self.assertEqual(again[0]["status"], "unchanged")

    def test_backtest_writes_scorecard_and_scan_uses_it(self):
        status = self.call(["market-status", str(self.database)])[1]
        scorecard = self.root / "scorecard.json"
        code, summary, error = self.call([
            "backtest", str(self.database), "--from", "2026-03-02", "--to", "2026-04-30",
            "--capital", "500000", "--out", str(scorecard),
        ])
        self.assertEqual((code, error), (0, None))
        self.assertEqual(set(summary["setup_status"]), set(json.loads(scorecard.read_text())["setups"]))
        code, report, error = self.call([
            "scan", str(self.database), "--as-of", status["bars"]["last"], "--capital", "500000",
            "--scorecard", str(scorecard),
        ])
        self.assertEqual((code, error), (0, None))
        self.assertEqual(report["as_of"], status["bars"]["last"])
        for candidate in report["candidates"]:
            self.assertIn(candidate["track_record"]["status"], {"PROVEN", "UNPROVEN"})
            self.assertGreater(candidate["plan"]["shares"], 0)
            self.assertLess(candidate["plan"]["stop"], candidate["plan"]["entry"])

    def test_scan_markdown_output(self):
        code, text, error = self.call(["scan", str(self.database), "--as-of", self.last_date(), "--format", "md"])
        self.assertEqual((code, error), (0, None))
        self.assertTrue(text.startswith("# Trade ideas as of"))
        self.assertIn("Regime:", text)

    def test_argument_errors_are_structured(self):
        for argv, code in (
            (["scan", str(self.database), "--as-of", "21-09-2026"], "ARGUMENT_INVALID"),
            (["scan", str(self.database), "--as-of", "2026-01-05", "--risk-per-trade", "0.5"], "ARGUMENT_INVALID"),
            (["backtest", str(self.database), "--from", "2026-05-01", "--to", "2026-04-01"], "ARGUMENT_INVALID"),
        ):
            with self.subTest(argv=argv):
                result = self.call(argv)
                self.assertEqual((result[0], result[2]["code"]), (2, code))

    def test_bad_market_file_reports_line(self):
        bad = self.root / "sec_bhavdata_full_bad.csv"
        fx.write_cm_full(bad, ["ABC, EQ, 99-Sep-2026, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1"])
        code, payload, error = self.call(["market-import", str(self.database), str(bad)])
        self.assertEqual((code, payload, error["code"], error["line"]), (2, None, "DATE_INVALID", 2))

    def test_events_file_labels_catalysts(self):
        events = self.root / "events.csv"
        events.write_text("symbol,date,type\nSYM01,2026-04-01,results\n", encoding="utf-8")
        code, _, error = self.call(["scan", str(self.database), "--as-of", self.last_date(), "--events", str(events)])
        self.assertEqual((code, error), (0, None))


if __name__ == "__main__":
    unittest.main()
