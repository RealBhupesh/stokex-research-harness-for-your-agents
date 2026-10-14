import json
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace

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
        self.assertEqual(live["overall"]["trades"], 0)
        self.assertEqual(live["excluded_from_live"], len(report["candidates"]))
        self.assertEqual(len(journal.closed_trades(self.db, forward_only=False)),
                         live["entries"].get("CLOSED", 0))
        again = scan(self.db, dates[-1], live=journal.live_records(self.db))
        for item in again["candidates"]:
            if item["setup"] in live["by_setup"]:
                self.assertIn("live", item["track_record"])

    def test_only_timely_records_can_enter_live_statistics(self):
        self.db.execute("INSERT INTO bars (symbol,series,trade_date,open,high,low,close,volume,available_at) "
                        "VALUES ('ABC','EQ','2026-06-01',100,101,99,100,1000,'2026-06-01T10:30:00Z')")
        candidate = {"symbol": "ABC", "setup": "BREAKOUT_52W", "setup_version": 1,
                     "rank": 1, "plan": {}, "jev": {"follow_through": .8}}
        report = {"as_of": "2026-06-01", "regime": {"label": "RISK_ON"},
                  "candidates": [candidate]}
        with patch.object(journal, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 6, 1, 11, tzinfo=timezone.utc)
            journal.record_scan(self.db, report)
        outcome = {"status": "CLOSED", "entry_date": "2026-06-02", "exit_date": "2026-06-03",
                   "r_multiple": 1.2, "return_pct": 1, "t1_hit": True, "sessions_held": 1,
                   "exit_reason": "T2"}
        self.db.execute("UPDATE journal SET outcome_json = ?", (json.dumps(outcome),))
        self.assertEqual(len(journal.closed_trades(self.db)), 1)
        self.assertEqual(journal.report(self.db)["record_origins"], {"FORWARD": 1})
        self.db.execute("UPDATE journal SET recorded_at = '2026-06-02T11:00:00Z'")
        self.assertEqual(journal.closed_trades(self.db), [])
        self.assertEqual(journal.report(self.db)["record_origins"], {"UNKNOWN": 1})

    def test_known_future_bars_prevent_live_origin(self):
        for day in ("2026-06-01", "2026-06-02"):
            self.db.execute("INSERT INTO bars (symbol,series,trade_date,open,high,low,close,volume,available_at) "
                            "VALUES ('ABC','EQ',?,100,101,99,100,1000,'2026-06-01T10:30:00Z')", (day,))
        report = {"as_of": "2026-06-01", "regime": {"label": "RISK_ON"},
                  "candidates": [{"symbol": "ABC", "setup": "X", "setup_version": 1,
                                  "rank": 1, "plan": {}}]}
        with patch.object(journal, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 6, 1, 11, tzinfo=timezone.utc)
            journal.record_scan(self.db, report)
        self.assertEqual(journal.report(self.db)["record_origins"], {"RETROSPECTIVE": 1})

    def test_intraday_and_legacy_records_are_not_live_evidence(self):
        candidate = {"symbol": "ABC", "setup": "BREAKOUT_52W", "setup_version": 1,
                     "rank": 1, "plan": {}}
        report = {"as_of": "2026-06-01", "regime": {"label": "RISK_ON"},
                  "candidates": [candidate]}
        with patch.object(journal, "datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 6, 1, 5, tzinfo=timezone.utc)
            journal.record_scan(self.db, report)
        self.assertEqual(journal.report(self.db)["record_origins"], {"RETROSPECTIVE": 1})
        self.db.execute("UPDATE journal SET judge_json = '{}'")
        self.assertEqual(journal.report(self.db)["record_origins"], {"UNKNOWN": 1})

    def test_price_units_preserve_replay_and_execution_session_scales(self):
        series = SimpleNamespace(adjustments=[{"ex_date": "2026-06-05", "factor": .5},
                                              {"ex_date": "2026-06-10", "factor": .5}])
        outcome = {"status": "CLOSED", "entry_date": "2026-06-04", "fill": 25,
                   "initial_stop": 24, "round_trip_cost_per_share": .1,
                   "legs": [{"date": "2026-06-06", "price": 30, "fraction": .5, "reason": "T1"},
                            {"date": "2026-06-11", "price": 35, "fraction": .5, "reason": "T2"}],
                   "r_multiple": 7.4, "return_pct": .296}
        result = journal._normalise_outcome_prices(outcome, series, "2026-06-03", "2026-06-12")
        self.assertEqual((result["fill"], result["initial_stop"], result["round_trip_cost_per_share"]),
                         (100, 96, .4))
        self.assertEqual([leg["price"] for leg in result["legs"]], [120, 140])
        self.assertEqual(result["simulated_session_prices"]["fill"], 100)
        self.assertEqual([leg["price"] for leg in result["simulated_session_prices"]["legs"]], [60, 35])
        self.assertEqual(result["replay_prices"]["fill"], outcome["fill"])
        self.assertEqual(result["r_multiple"], outcome["r_multiple"])
        self.assertEqual(outcome["legs"][0]["price"], 30)  # caller input stays frozen

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
        self.assertLess(abs(outcome["fill"] - 1055), 6)
        self.assertEqual(outcome["price_units"], "SIGNAL_SESSION")
        self.assertEqual(outcome["price_reference_date"], scan_day.isoformat())
        self.assertAlmostEqual(outcome["replay_adjustment_factor"], .5)
        self.assertAlmostEqual(outcome["replay_prices"]["fill"] * 2, outcome["fill"])
        self.assertAlmostEqual(outcome["initial_stop"], plan["stop"])
        self.assertAlmostEqual(outcome["simulated_session_prices"]["fill"], outcome["fill"])
        self.assertEqual(outcome["share_units"], "NOT_RECONSTRUCTED")
        for leg, replay_leg in zip(outcome["legs"], outcome["replay_prices"]["legs"]):
            self.assertAlmostEqual(leg["price"], replay_leg["price"] * 2)
        before = dict(outcome)
        journal.update_outcomes(self.db, days[-1].isoformat())
        again = json.loads(self.db.execute("SELECT outcome_json FROM journal").fetchone()[0])
        self.assertEqual(before, again)
        self.assertGreater(outcome["r_multiple"], -1.0)


if __name__ == "__main__":
    unittest.main()
