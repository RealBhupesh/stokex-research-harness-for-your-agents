import pathlib
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.market.importers import import_market_file
from stockex.market.queries import trading_dates
from stockex.market.schema import open_market_db
from stockex.signals.scan import _effective_day, scan


class ScanContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls.directory.name)
        cls.db = open_market_db(cls.root / "m.sqlite3")
        for path in fx.generate_market(cls.root, symbols=30, days=280, fo_symbols=6, seed=8):
            import_market_file(cls.db, path)
        cls.dates = trading_dates(cls.db, "2000-01-01", "2100-01-01")
        cls.day = next(d for d in reversed(cls.dates[200:]) if len(scan(cls.db, d)["candidates"]) >= 3)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.directory.cleanup()

    def test_sector_strength_cap_and_announcement_catalyst(self):
        base = scan(self.db, self.day, top=50)
        self.assertTrue(any("index constituent" in note for note in base["notes"]))
        target = base["candidates"][0]["symbol"]

        members = self.root / "ind_nifty500list.csv"
        fx.write_index_members(members, [(f"SYM{i:02d}", "Banks") for i in range(30)])
        import_market_file(self.db, members)
        announcements = self.root / "announcements.csv"
        day = date.fromisoformat(self.day)
        fx.write_announcements(announcements, [(target, "Receipt of order worth Rs 400 crore", day, "11:00:00")])
        import_market_file(self.db, announcements)

        report = scan(self.db, self.day, top=50)
        self.assertLessEqual(len(report["candidates"]), 2)
        capped = [r for r in report["rejected"] if r["code"] == "SECTOR_CAP"]
        self.assertEqual(len(capped), len(base["candidates"]) - len(report["candidates"]))
        everyone = {c["symbol"]: c for c in report["candidates"]}
        for candidate in report["candidates"]:
            self.assertEqual(candidate["sector"], "Banks")
            self.assertIn("rs_sector20", candidate["sector_strength"])
        if target in everyone:
            catalyst = everyone[target]["catalyst"]
            self.assertEqual((catalyst["type"], catalyst["source"]), ("ORDER_WIN", "NSE announcement"))
        uncapped = scan(self.db, self.day, top=50, risk_params={"max_per_sector": 0})
        self.assertEqual(len(uncapped["candidates"]), len(base["candidates"]))
        catalysts = {c["symbol"]: c["catalyst"] for c in uncapped["candidates"]}
        self.assertEqual(catalysts[target]["type"], "ORDER_WIN")

    def test_effective_day_respects_end_of_day_cutoff(self):
        days = ["2026-09-21", "2026-09-22", "2026-09-23"]
        self.assertEqual(_effective_day("2026-09-21T10:00:00Z", days), "2026-09-21")  # 15:30 IST
        self.assertEqual(_effective_day("2026-09-21T14:00:00Z", days), "2026-09-22")  # 19:30 IST
        self.assertEqual(_effective_day("2026-09-19T05:00:00Z", days), "2026-09-21")  # Saturday
        self.assertIsNone(_effective_day("2026-09-24T05:00:00Z", days))


if __name__ == "__main__":
    unittest.main()
