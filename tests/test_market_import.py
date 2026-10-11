from datetime import date
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.market.importers import MarketImportError, import_market_file, parse_date
from stockex.market.queries import (
    coverage, deals_between, futures_history, index_closes, load_history, option_chain, restrictions_on,
)
from stockex.market.schema import open_market_db
from stockex.store.database import PointInTimeStore


D1, D2 = date(2026, 9, 21), date(2026, 9, 22)
EXPIRY, NEXT_EXPIRY, FAR_EXPIRY = date(2026, 9, 29), date(2026, 10, 27), date(2026, 11, 24)


class MarketImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.db = open_market_db(self.root / "m.sqlite3")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def path(self, name):
        return self.root / name

    def test_parse_date_spellings(self):
        for text in ("2026-09-21", "21-Sep-2026", "21-SEP-2026", "21-09-2026", "21/09/2026"):
            self.assertEqual(parse_date(text), "2026-09-21")

    def test_cm_full_with_padding_delivery_and_series_filter(self):
        file = self.path("sec_bhavdata_full_21092026.csv")
        fx.write_cm_full(file, [
            fx.cm_full_line("ABC", D1, 100, 105, 99, 104, 100, 50_000, deliv_pct=62.5),
            fx.cm_full_line("ABC", D1, 100, 105, 99, 104, 100, 10, series="N1"),
            fx.cm_full_line("XYZ", D1, 50, 51, 49, 50, 50, 1000, deliv_pct=None, series="BE"),
            fx.cm_full_line("BAD", D1, 10, 9, 11, 10, 10, 5),
        ])
        result = import_market_file(self.db, file)
        self.assertEqual((result["kind"], result["written"]), ("cm-full", 2))
        self.assertEqual(result["skipped"], {"PRICE_IMPLAUSIBLE": 1, "SERIES_EXCLUDED": 1})
        abc = load_history(self.db, "ABC", "2026-09-21")
        self.assertEqual((abc.close, abc.delivery_pct, abc.delivery_qty), ([104.0], [62.5], [31250]))
        self.assertAlmostEqual(abc.value[0], 104 * 50_000, delta=1)
        self.assertIsNone(load_history(self.db, "XYZ", "2026-09-21").delivery_pct[0])

    def test_reimport_is_unchanged_and_udiff_fills_isin_without_overwriting(self):
        full = self.path("sec_bhavdata_full_21092026.csv")
        fx.write_cm_full(full, [fx.cm_full_line("ABC", D1, 100, 105, 99, 104, 100, 50_000, deliv_pct=60)])
        import_market_file(self.db, full)
        self.assertEqual(import_market_file(self.db, full)["status"], "unchanged")
        udiff = self.path("BhavCopy_NSE_CM_0_0_0_20260921_F_0000.csv")
        fx.write_udiff(udiff, [fx.udiff_line(D1, "CM", "STK", "ABC", series="EQ", o=100, h=105, l=99, c=104,
                                             prev=100, volume=50_000, value=5.2e6, isin="INE000A01001")])
        self.assertEqual(import_market_file(self.db, udiff)["kind"], "udiff")
        row = self.db.execute("SELECT isin, delivery_pct FROM bars WHERE symbol='ABC'").fetchone()
        self.assertEqual(tuple(row), ("INE000A01001", 60.0))

    def test_fo_udiff_keeps_futures_and_nearest_option_expiries(self):
        file = self.path("BhavCopy_NSE_FO_0_0_0_20260921_F_0000.csv")
        lines = [
            fx.udiff_line(D1, "FO", "STF", "ABC", expiry=EXPIRY, c=105, oi=1_000_000, oi_change=50_000, volume=900),
            fx.udiff_line(D1, "FO", "STF", "ABC", expiry=NEXT_EXPIRY, c=106, oi=200_000, volume=100),
            fx.udiff_line(D1, "FO", "IDF", "NIFTY", expiry=EXPIRY, c=25000, oi=10, volume=1),
        ]
        for expiry in (EXPIRY, NEXT_EXPIRY, FAR_EXPIRY):
            for option in ("CE", "PE"):
                lines.append(fx.udiff_line(D1, "FO", "STO", "ABC", expiry=expiry, strike=100, option=option,
                                           c=5, underlying=104, oi=10_000, volume=10))
        fx.write_udiff(file, lines)
        result = import_market_file(self.db, file, option_expiries=2)
        self.assertEqual(result["skipped"], {"OPTION_EXPIRY_EXCLUDED": 2})
        futures = futures_history(self.db, "2026-09-21", symbols=["ABC"])["ABC"]["2026-09-21"]
        self.assertEqual((futures["near_oi"], futures["next_oi"], futures["total_oi"]), (1_000_000, 200_000, 1_200_000))
        chain = option_chain(self.db, "ABC", "2026-09-21")
        self.assertEqual({(row["instrument"], row["expiry"]) for row in chain},
                         {("CE", EXPIRY.isoformat()), ("PE", EXPIRY.isoformat())})

    def test_option_retention_modes(self):
        lines = [fx.udiff_line(D1, "FO", "STF", "ABC", expiry=EXPIRY, c=105, oi=1000, volume=1)]
        for expiry in (EXPIRY, NEXT_EXPIRY):
            lines.append(fx.udiff_line(D1, "FO", "STO", "ABC", expiry=expiry, strike=100, option="CE",
                                       c=5, underlying=104, oi=10, volume=1))
        for name, expiries, expected in (("default", 1, {"OPTION_EXPIRY_EXCLUDED": 1}),
                                         ("none", 0, {"OPTIONS_EXCLUDED": 2}), ("all", None, {})):
            with self.subTest(name=name):
                db = open_market_db(self.root / f"{name}.sqlite3")
                file = self.path(f"BhavCopy_NSE_FO_0_0_0_20260921_F_{name}.csv")
                fx.write_udiff(file, lines)
                kwargs = {} if name == "default" else {"option_expiries": expiries}
                self.assertEqual(import_market_file(db, file, **kwargs)["skipped"], expected)
                db.close()

    def test_index_deals_and_ban_list(self):
        index = self.path("ind_close_all_21092026.csv")
        fx.write_index(index, [fx.index_line("Nifty 50", D1, 25000, 25100, 24900, 25050),
                               fx.index_line("India VIX", D1, 12, 13, 11, 12.5)])
        bulk = self.path("bulk.csv")
        fx.write_deals(bulk, [fx.deal_line(D1, "ABC", "Some  Fund Ltd", "BUY", 1_234_567, 101.5)])
        block = self.path("block_deals.csv")
        fx.write_deals(block, [fx.deal_line(D1, "ABC", "Other Fund", "SELL", 10_000, 100)])
        ban = self.path("fo_secban_22092026.csv")
        fx.write_ban(ban, D2, ["XYZ"])
        kinds = [import_market_file(self.db, file)["kind"] for file in (index, bulk, block, ban)]
        self.assertEqual(kinds, ["index", "bulk", "block", "fo-ban"])
        self.assertEqual(index_closes(self.db, "NIFTY 50", "2026-09-21"), {"2026-09-21": 25050.0})
        deals = deals_between(self.db, "2026-09-21", "2026-09-21", symbol="ABC")
        self.assertEqual([(d["kind"], d["client"], d["quantity"]) for d in deals],
                         [("BLOCK", "OTHER FUND", 10_000), ("BULK", "SOME FUND LTD", 1_234_567)])
        self.assertEqual(restrictions_on(self.db, "2026-09-22"), {"XYZ": ["FO_BAN"]})
        self.assertEqual(restrictions_on(self.db, "2026-09-23"), {})

    def test_restrictions_file(self):
        file = self.path("asm.csv")
        file.write_text("list,symbol,stage,from_date,to_date\nASM,abc,LT-2,2026-09-01,\n", encoding="utf-8")
        import_market_file(self.db, file)
        self.assertEqual(restrictions_on(self.db, "2026-09-21"), {"ABC": ["ASM:LT-2"]})

    def test_structural_error_rolls_back_whole_file_with_line(self):
        file = self.path("sec_bhavdata_full_21092026.csv")
        good = fx.cm_full_line("ABC", D1, 100, 105, 99, 104, 100, 50_000, deliv_pct=60)
        bad = fx.cm_full_line("DEF", D1, 100, 105, 99, 104, 100, 50_000).replace(" 21-Sep-2026", " 31-Sep-2026")
        fx.write_cm_full(file, [good, bad])
        with self.assertRaises(MarketImportError) as caught:
            import_market_file(self.db, file)
        self.assertEqual((caught.exception.line, caught.exception.code), (3, "DATE_INVALID"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM market_imports").fetchone()[0], 0)

    def test_missing_columns_and_unknown_kind(self):
        file = self.path("x.csv")
        file.write_text("foo,bar\n1,2\n", encoding="utf-8")
        with self.assertRaises(MarketImportError) as caught:
            import_market_file(self.db, file)
        self.assertEqual(caught.exception.code, "KIND_UNKNOWN")
        file.write_text("SYMBOL,SERIES,DATE1,CLOSE_PRICE\nABC,EQ,21-Sep-2026,1\n", encoding="utf-8")
        with self.assertRaises(MarketImportError) as caught:
            import_market_file(self.db, file)
        self.assertEqual(caught.exception.code, "COLUMNS_MISSING")

    def test_point_in_time_reads_exclude_later_rows(self):
        for day, close, prev in ((D1, 104, 100), (D2, 110, 104)):
            file = self.path(f"sec_bhavdata_full_{day:%d%m%Y}.csv")
            fx.write_cm_full(file, [fx.cm_full_line("ABC", day, 100, 111, 99, close, prev, 1000, deliv_pct=50)])
            import_market_file(self.db, file)
        self.assertEqual(load_history(self.db, "ABC", "2026-09-21").close, [104.0])
        self.assertEqual(load_history(self.db, "ABC", "2026-09-22").close, [104.0, 110.0])
        late = self.path("late.csv")
        fx.write_cm_full(late, [fx.cm_full_line("LATE", D1, 10, 11, 9, 10, 10, 100, deliv_pct=50)])
        import_market_file(self.db, late, available_at="2026-09-23T04:00:00Z")
        self.assertEqual(len(load_history(self.db, "LATE", "2026-09-22")), 0)
        status = coverage(self.db)
        self.assertEqual((status["bars"]["first"], status["bars"]["last"]), ("2026-09-21", "2026-09-22"))

    def test_market_tables_share_a_file_with_the_evidence_store(self):
        path = self.root / "shared.sqlite3"
        with PointInTimeStore.open(path) as store:
            self.assertTrue(store.integrity_report()["valid"])
        connection = open_market_db(path)
        connection.close()
        with PointInTimeStore.open(path) as store:
            self.assertTrue(store.integrity_report()["valid"])


if __name__ == "__main__":
    unittest.main()
