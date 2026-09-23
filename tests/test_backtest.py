import pathlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.backtest import build_scorecard, data_fingerprint, run_backtest, simulate_trade
from stockex.market.importers import import_market_file
from stockex.market.queries import trading_dates
from stockex.market.schema import open_market_db
from stockex.signals.scan import _track_record, scan


def file_date(path):
    digits = re.search(r"(\d{8})", path.name)[1]
    if path.name.startswith("BhavCopy"):
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return f"{digits[4:]}-{digits[2:4]}-{digits[:2]}"


PLAN = {"entry": 100.0, "stop": 95.0, "t1": 107.5, "t2": 115.0, "time_stop_sessions": 5}


def series_after(*bars):
    """Signal bar followed by the given (open, high, low, close) bars."""
    rows = [(99, 99.9, 98, 99.5)] + list(bars)
    return fx.make_series([(o, h, l, c, 1000, 50.0) for o, h, l, c in rows])


class SimulateTradeTests(unittest.TestCase):
    def test_fill_at_trigger_then_t1_and_t2(self):
        trade = simulate_trade(series_after((99.5, 101, 99, 100.5), (101, 108, 100.5, 107), (107, 116, 106, 115)),
                               0, PLAN, cost_bps=0)
        self.assertEqual((trade["fill"], trade["exit_reason"]), (100.0, "T2"))
        self.assertAlmostEqual(trade["r_multiple"], (0.5 * 7.5 + 0.5 * 15) / 5)
        self.assertEqual([leg["reason"] for leg in trade["legs"]], ["T1", "T2"])

    def test_gap_through_trigger_fills_at_open_and_costs_reduce_r(self):
        trade = simulate_trade(series_after((102, 103, 101, 102.5), (102.5, 103, 102, 102.5)), 0,
                               dict(PLAN, time_stop_sessions=2), cost_bps=50)
        self.assertEqual((trade["fill"], trade["exit_reason"]), (102.0, "TIME_STOP"))
        self.assertAlmostEqual(trade["r_multiple"], (0.5 - 102 * 0.005) / 7)

    def test_no_fill_expires(self):
        trade = simulate_trade(series_after((99, 99.8, 98, 99)), 0, PLAN, cost_bps=0)
        self.assertFalse(trade["filled"])

    def test_bar_touching_stop_and_target_counts_as_stop(self):
        trade = simulate_trade(series_after((99.5, 101, 99, 100.5), (100, 116, 94, 110)), 0, PLAN, cost_bps=0)
        self.assertEqual(trade["exit_reason"], "STOP")
        self.assertAlmostEqual(trade["r_multiple"], -1.0)

    def test_gap_below_stop_exits_at_open(self):
        trade = simulate_trade(series_after((99.5, 101, 99, 100.5), (90, 92, 89, 91)), 0, PLAN, cost_bps=0)
        self.assertEqual((trade["exit_reason"], trade["legs"][-1]["price"]), ("GAP_STOP", 90))
        self.assertAlmostEqual(trade["r_multiple"], -2.0)

    def test_after_t1_stop_moves_to_breakeven(self):
        trade = simulate_trade(series_after((99.5, 101, 99, 100.5), (101, 108, 100.5, 107), (106, 106.5, 99, 99.5)),
                               0, PLAN, cost_bps=0)
        self.assertEqual([leg["reason"] for leg in trade["legs"]], ["T1", "TRAIL_STOP"])
        self.assertGreater(trade["r_multiple"], 0)

    def test_gap_above_target_on_entry_day_never_books_below_fill(self):
        trade = simulate_trade(series_after((120, 121, 119, 120)), 0, PLAN, cost_bps=0)
        self.assertEqual(trade["fill"], 120)
        self.assertTrue(all(leg["price"] >= 120 for leg in trade["legs"]))


class WalkForwardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = root = pathlib.Path(cls.directory.name)
        cls.db = open_market_db(root / "m.sqlite3")
        cls.files = fx.generate_market(root, symbols=25, days=280, fo_symbols=8, seed=11)
        for path in cls.files:
            import_market_file(cls.db, path)
        cls.dates = trading_dates(cls.db, "2000-01-01", "2100-01-01")

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.directory.cleanup()

    def test_backtest_is_deterministic_and_reports_every_setup_in_scorecard(self):
        start, end = self.dates[200], self.dates[-6]
        first = run_backtest(self.db, start, end, max_positions=3)
        second = run_backtest(self.db, start, end, max_positions=3)
        self.assertEqual(first["overall"], second["overall"])
        self.assertEqual(first["portfolio"]["equity_curve"], second["portfolio"]["equity_curve"])
        self.assertGreater(first["overall"]["trades"], 0)
        self.assertTrue(all(t["signal_date"] <= end for t in first["trades"]))
        self.assertLessEqual(first["portfolio"]["trades_taken"], first["overall"]["trades"])
        card = build_scorecard(first, data_fingerprint(self.db, start, end))
        self.assertEqual(len(card["setups"]), 9)
        for entry in card["setups"].values():
            expected = "PROVEN" if entry["overall"]["trades"] >= 30 and (entry["overall"].get("expectancy_r") or 0) > 0 \
                else "UNPROVEN"
            self.assertEqual(entry["status"], expected)

    def test_scan_does_not_see_future_bars(self):
        day = self.dates[240]
        truncated = open_market_db(self.root / "truncated.sqlite3")
        try:
            for path in self.files:
                if file_date(path) <= day:
                    import_market_file(truncated, path)
            with_future = scan(self.db, day, risk_params={"capital": 1_000_000})
            without_future = scan(truncated, day, risk_params={"capital": 1_000_000})
        finally:
            truncated.close()
        self.assertEqual(with_future["candidates"], without_future["candidates"])
        self.assertEqual(with_future["regime"], without_future["regime"])

    def test_scan_notes_in_sample_scorecard(self):
        card = {"period": {"to": self.dates[-1]}, "setups": {}}
        report = scan(self.db, self.dates[-10], scorecard=card)
        self.assertTrue(any("in-sample" in note for note in report["notes"]))


class TrackRecordTests(unittest.TestCase):
    def card(self, trades, expectancy, version=1):
        stats = {"trades": trades, "expectancy_r": expectancy, "hit_rate": 0.5}
        return {"setups": {"BREAKOUT_52W": {"version": version, "overall": stats, "by_regime": {"RISK_ON": stats}}}}

    def test_status_rules(self):
        self.assertEqual(_track_record(None, "BREAKOUT_52W", "RISK_ON")["status"], "NO_SCORECARD")
        self.assertEqual(_track_record(self.card(40, 0.2), "BREAKOUT_52W", "RISK_ON")["status"], "PROVEN")
        self.assertEqual(_track_record(self.card(10, 0.9), "BREAKOUT_52W", "RISK_ON")["status"], "UNPROVEN")
        self.assertEqual(_track_record(self.card(40, -0.1), "BREAKOUT_52W", "RISK_ON")["status"], "UNPROVEN")
        self.assertEqual(_track_record(self.card(40, 0.2, version=0), "BREAKOUT_52W", "RISK_ON")["status"], "UNPROVEN")
        record = _track_record(self.card(40, 0.2), "BREAKOUT_52W", "RISK_OFF")
        self.assertEqual(record["basis"], "overall")


if __name__ == "__main__":
    unittest.main()
