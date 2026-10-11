import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import market_fixtures as fx
from stockex.backtest import journal
from stockex.backtest.engine import simulate_trade
from stockex.market.importers import import_market_file
from stockex.market.queries import load_history, trading_dates
from stockex.market.schema import open_market_db
from stockex.signals.scan import scan


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.db = open_market_db(self.root / "m.sqlite3")

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def test_record_update_and_report_match_the_simulator(self):
        for path in fx.generate_market(self.root, symbols=30, days=280, fo_symbols=5, seed=4):
            import_market_file(self.db, path)
        dates = trading_dates(self.db, "2000-01-01", "2100-01-01")
        day = next(d for d in dates[200:-20] if scan(self.db, d)["candidates"])
        report = scan(self.db, day, risk_params={"capital": 500_000})
        self.assertEqual(journal.record_scan(self.db, report), len(report["candidates"]))
        self.assertEqual(journal.record_scan(self.db, report), 0)

        first = journal.update_outcomes(self.db, dates[dates.index(day) + 1])
        self.assertEqual(sum(first.values()), len(report["candidates"]))
        final = journal.update_outcomes(self.db, dates[-1])
        self.assertEqual(final["open"], 0)

        candidate = report["candidates"][0]
        series = load_history(self.db, candidate["symbol"], dates[-1])
        expected = simulate_trade(series, series.dates.index(day), candidate["plan"], cost_bps=0)
        stored = json.loads(self.db.execute(
            "SELECT outcome_json FROM journal WHERE symbol = ? AND scan_date = ?", (candidate["symbol"], day)
        ).fetchone()[0])
        if expected["filled"]:
            self.assertEqual((stored["status"], stored["r_multiple"]), ("CLOSED", expected["r_multiple"]))
        else:
            self.assertEqual(stored["status"], "NOT_FILLED")

        live = journal.report(self.db)
        self.assertEqual(sum(live["entries"].values()), len(report["candidates"]))
        self.assertEqual(live["overall"]["trades"], live["entries"].get("CLOSED", 0))
        again = scan(self.db, dates[-1], live=journal.live_records(self.db))
        for item in again["candidates"]:
            if item["setup"] in live["by_setup"]:
                self.assertIn("live", item["track_record"])

    def test_split_after_the_scan_rescales_the_frozen_plan(self):
        days = fx.weekdays(fx.date(2026, 6, 1), 12)
        scan_day, ex = days[5], days[8]
        previous = 1000.0
        for day in days:
            price = 1000.0 + 10 * days.index(day)
            if day >= ex:
                price /= 2
            published = previous / 2 if day == ex else previous
            file = self.root / f"sec_bhavdata_full_{day:%d%m%Y}.csv"
            fx.write_cm_full(file, [fx.cm_full_line("ABC", day, price, price * 1.002, price * 0.998, price,
                                                    published, 100_000, deliv_pct=50)])
            import_market_file(self.db, file)
            previous = price
        plan = {"entry": 1055.0, "stop": 1000.0, "t1": 1500.0, "t2": 2000.0, "time_stop_sessions": 5,
                "round_trip_cost_per_share": 0.0}
        self.db.execute(
            "INSERT INTO journal VALUES (?, 'ABC', 'BREAKOUT_52W', 1, 1, ?, '{}', 'RISK_ON', 'x', NULL)",
            (scan_day.isoformat(), json.dumps(plan)),
        )
        journal.update_outcomes(self.db, days[-1].isoformat())
        outcome = json.loads(self.db.execute("SELECT outcome_json FROM journal").fetchone()[0])
        self.assertEqual(outcome["status"], "CLOSED")
        self.assertEqual(outcome["exit_reason"], "TIME_STOP")
        self.assertLess(abs(outcome["fill"] - 527.5), 3)  # entry 1055 halved by the 1:2 split
        self.assertGreater(outcome["r_multiple"], -1.0)


if __name__ == "__main__":
    unittest.main()
