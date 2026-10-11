import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.market.corporate import classify_announcement, parse_purpose
from stockex.market.importers import import_market_file
from stockex.market.queries import announcements_between, coverage, load_history, sector_map
from stockex.market.schema import open_market_db
from stockex.signals.indicators import compute_features


class PurposeTests(unittest.TestCase):
    def test_parse_purpose(self):
        cases = {
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share": ("SPLIT", 0.2),
            "Face Value Split (Sub-Division) - From Re 1/- Per Share To Re 0.50/- Per Share": ("SPLIT", 0.5),
            "Bonus 1:1": ("BONUS", 0.5),
            "BONUS 3:2": ("BONUS", 0.4),
            "Consolidation Of Shares From Rs 1/- To Rs 10/-": ("CONSOLIDATION", 10.0),
            "Dividend - Rs 5 Per Share": None,
            "Annual General Meeting": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_purpose(text), expected)

    def test_classify_announcement(self):
        self.assertEqual(classify_announcement("Outcome of Board Meeting - Financial Results"), "RESULTS")
        self.assertEqual(classify_announcement("Receipt of order worth Rs 500 crore"), "ORDER_WIN")
        self.assertEqual(classify_announcement("SEBI order in the matter of XYZ"), "LITIGATION")
        self.assertEqual(classify_announcement("Updates"), "OTHER")


class AdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.db = open_market_db(self.root / "m.sqlite3")
        self.days = fx.weekdays(fx.date(2026, 6, 1), 60)
        self.ex = self.days[40]

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def import_split_history(self, *, adjusted_prev_close=True):
        price, previous = 1000.0, 1000.0
        for index, day in enumerate(self.days):
            if day == self.ex:
                price /= 5  # 1:5 split
                published_prev = previous / 5 if adjusted_prev_close else previous
            else:
                published_prev = previous
            close = price * (1.001 if index % 2 else 0.999)
            volume = 100_000 * (5 if day >= self.ex else 1)
            file = self.root / f"sec_bhavdata_full_{day:%d%m%Y}.csv"
            fx.write_cm_full(file, [fx.cm_full_line("ABC", day, close, close * 1.01, close * 0.99, close,
                                                    published_prev, volume, deliv_pct=50)])
            import_market_file(self.db, file)
            previous = close

    def test_explicit_split_back_adjusts_prices_and_volume(self):
        self.import_split_history(adjusted_prev_close=False)
        file = self.root / "corp_actions.csv"
        fx.write_corp_actions(file, [("ABC", "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", self.ex)])
        self.assertEqual(import_market_file(self.db, file)["written"], 1)
        series = load_history(self.db, "ABC", self.days[-1].isoformat())
        i = series.dates.index(self.ex.isoformat())
        self.assertAlmostEqual(series.close[i - 1] / series.close[i], 1.0, delta=0.01)
        self.assertEqual(series.volume[i - 1], 500_000)
        self.assertEqual([a["source"] for a in series.adjustments], ["CORPORATE_ACTIONS"])
        features = compute_features(series)
        self.assertLess(abs(features.columns["ret1"][i]), 0.01)
        raw = load_history(self.db, "ABC", self.days[-1].isoformat(), adjust=False)
        self.assertLess(raw.close[i] / raw.close[i - 1], 0.25)

    def test_inferred_from_prev_close_when_file_missing(self):
        self.import_split_history(adjusted_prev_close=True)
        series = load_history(self.db, "ABC", self.days[-1].isoformat())
        self.assertEqual([(a["kind"], a["source"]) for a in series.adjustments], [("INFERRED", "PREV_CLOSE")])
        self.assertAlmostEqual(series.adjustments[0]["factor"], 0.2, places=3)

    def test_adjustment_is_point_in_time(self):
        self.import_split_history(adjusted_prev_close=True)
        file = self.root / "corp_actions.csv"
        fx.write_corp_actions(file, [("ABC", "Bonus 4:1", self.ex)])
        import_market_file(self.db, file)
        before = load_history(self.db, "ABC", self.days[39].isoformat())
        self.assertEqual(before.adjustments, [])
        after = load_history(self.db, "ABC", self.days[-1].isoformat())
        self.assertEqual([a["source"] for a in after.adjustments], ["CORPORATE_ACTIONS"])
        self.assertEqual(coverage(self.db)["corporate_actions"], 1)


class ReferenceDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.db = open_market_db(self.root / "m.sqlite3")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_index_members_and_sector_map(self):
        file = self.root / "ind_nifty500list.csv"
        fx.write_index_members(file, [("ABC", "Capital Goods"), ("XYZ", "Information Technology")])
        result = import_market_file(self.db, file)
        self.assertEqual((result["kind"], result["written"]), ("index-members", 2))
        self.assertEqual(sector_map(self.db), {"ABC": "Capital Goods", "XYZ": "Information Technology"})
        self.assertEqual(self.db.execute("SELECT DISTINCT index_name FROM index_members").fetchone()[0], "NIFTY500")

    def test_announcements_import_classify_and_point_in_time(self):
        day = fx.date(2026, 9, 22)
        file = self.root / "CF-AN-equities.csv"
        fx.write_announcements(file, [
            ("ABC", "Outcome of Board Meeting - Financial Results", day, "16:05:00"),
            ("ABC", "Receipt of order worth Rs 300 crore", day, "19:30:00"),
        ])
        result = import_market_file(self.db, file)
        self.assertEqual((result["kind"], result["written"]), ("announcements", 2))
        rows = announcements_between(self.db, "2026-09-22", "2026-09-22")["ABC"]
        self.assertEqual([(r["category"], r["broadcast_at"]) for r in rows],
                         [("RESULTS", "2026-09-22T10:35:00Z")])
        later = announcements_between(self.db, "2026-09-22", "2026-09-23")["ABC"]
        self.assertEqual([r["category"] for r in later], ["RESULTS", "ORDER_WIN"])


if __name__ == "__main__":
    unittest.main()


class JevAnnouncementTests(unittest.TestCase):
    def test_jev_reclassifies_only_keyword_other_rows(self):
        from stockex.jev.announcements import classify_with_jev

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = pathlib.Path(directory.name)
        db = open_market_db(root / "m.sqlite3")
        self.addCleanup(db.close)
        day = fx.date(2026, 9, 22)
        file = root / "announcements.csv"
        fx.write_announcements(file, [
            ("ABC", "Press Release", day, "10:00:00"),
            ("ABC", "Updates", day, "11:00:00"),
            ("ABC", "Financial Results for the quarter", day, "12:00:00"),
        ])
        import_market_file(db, file)

        class Stub:
            model = "jev-test"
            calls = []

            def evaluate(self, state, questions):
                Stub.calls.append(state["subject"])
                choice, confidence = ("ORDER_WIN", 0.9) if state["subject"] == "Press Release" else ("BUYBACK", 0.3)
                return {"model": "jev-1", "answers": {
                    "category": {"type": "choice", "choice": choice, "confidence": confidence},
                    "material": {"type": "noul", "noul": 0.7}}}

        counts = classify_with_jev(db, Stub())
        self.assertEqual(counts, {"examined": 2, "reclassified": 1, "kept_other": 1, "errors": 0})
        self.assertEqual(sorted(Stub.calls), ["Press Release", "Updates"])
        rows = dict(db.execute("SELECT subject, category || '/' || category_source FROM announcements").fetchall())
        self.assertEqual(rows["Press Release"], "ORDER_WIN/JEV")
        self.assertEqual(rows["Updates"], "OTHER/JEV_LOW_CONFIDENCE")
        self.assertEqual(rows["Financial Results for the quarter"], "RESULTS/KEYWORD")
        self.assertEqual(classify_with_jev(db, Stub())["examined"], 0)
