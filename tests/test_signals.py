import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import market_fixtures as fx
from finance_helpers import size_cash_trade
from stockex.signals.fo import bs_price, fo_features, implied_vol, oi_quadrant, option_context
from stockex.signals.indicators import atr, compute_features, rolling_max, rolling_min, sma
from stockex.signals.regime import classify_regime
from stockex.signals.risk_plan import Rejection, TradePlan, build_plan
from stockex.signals.setups import SETUPS, SetupContext, Signal, evaluate_setups


def run(series, *, bench_return=0.0, fo=None, deals=(), events=None, regime="RISK_ON", names=None):
    f = compute_features(series, fx.benchmark_for(series, bench_return))
    ctx = SetupContext(fo=fo, deals=list(deals), events=events or {}, regime=regime)
    return f, evaluate_setups(f, len(series) - 1, ctx, names)


def names(signals):
    return [s.setup for s in signals]


class IndicatorTests(unittest.TestCase):
    def test_rolling_windows_and_prior_exclusion(self):
        values = [3, 1, 4, 1, 5, 9, 2, 6]
        self.assertEqual(rolling_max(values, 3), [3, 3, 4, 4, 5, 9, 9, 9])
        self.assertEqual(rolling_max(values, 3, prior=True), [None, 3, 3, 4, 4, 5, 9, 9])
        self.assertEqual(rolling_min(values, 3, prior=True), [None, 3, 1, 1, 1, 1, 1, 2])
        self.assertEqual(sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_atr_uses_true_range_with_wilder_smoothing(self):
        result = atr([2, 3, 4], [1, 1, 2], [1.5, 2.5, 3], 2)
        self.assertEqual(result[:2], [None, 1.5])
        self.assertAlmostEqual(result[2], (1.5 + 2) / 2)

    def test_features_do_not_look_ahead(self):
        bars = fx.trend_bars(100, 300, 0.001, wiggle=0.01)
        series = fx.make_series(bars)
        bench = fx.benchmark_for(series, 0.0005)
        full = compute_features(series, bench)
        for cut in (120, 200, 299):
            partial = compute_features(series.truncated(cut + 1), bench)
            self.assertEqual(partial.at(cut), full.at(cut))


class FoTests(unittest.TestCase):
    def test_quadrants(self):
        self.assertEqual(oi_quadrant(0.02, 0.05), "LONG_BUILDUP")
        self.assertEqual(oi_quadrant(-0.02, 0.05), "SHORT_BUILDUP")
        self.assertEqual(oi_quadrant(0.02, -0.05), "SHORT_COVERING")
        self.assertEqual(oi_quadrant(-0.02, -0.05), "LONG_UNWINDING")
        self.assertEqual(oi_quadrant(0.001, 0.05), "NEUTRAL")
        self.assertEqual(oi_quadrant(None, 0.05), "NEUTRAL")

    def test_implied_vol_round_trip_and_option_context(self):
        price = bs_price("CE", 100, 100, 30 / 365, 0.3)
        self.assertAlmostEqual(implied_vol("CE", price, 100, 100, 30 / 365), 0.3, places=4)
        self.assertIsNone(implied_vol("CE", 0.0, 100, 100, 0.1))
        chain = [
            {"instrument": "CE", "expiry": "2026-10-21", "strike": 100.0, "settle": bs_price("CE", 101, 100, 30 / 365, 0.25),
             "close": None, "open_interest": 500, "underlying": 101.0},
            {"instrument": "PE", "expiry": "2026-10-21", "strike": 100.0, "settle": bs_price("PE", 101, 100, 30 / 365, 0.25),
             "close": None, "open_interest": 1000, "underlying": 101.0},
            {"instrument": "CE", "expiry": "2026-10-21", "strike": 110.0, "settle": 0.5, "close": None,
             "open_interest": 3000, "underlying": 101.0},
        ]
        context = option_context(chain, "2026-09-21")
        self.assertAlmostEqual(context["pcr"], 1000 / 3500)
        self.assertEqual((context["call_wall"], context["put_wall"]), (110.0, 100.0))
        self.assertAlmostEqual(context["atm_iv"], 0.25, places=3)

    def test_fo_features_align_and_compute_changes(self):
        dates = ["2026-09-21", "2026-09-22"]
        futures = {
            "2026-09-21": {"near_expiry": "2026-09-29", "near_price": 100.0, "near_oi": 900, "next_oi": 100, "total_oi": 1000, "volume": 1},
            "2026-09-22": {"near_expiry": "2026-09-29", "near_price": 103.0, "near_oi": 800, "next_oi": 400, "total_oi": 1200, "volume": 1},
        }
        fo = fo_features(dates, futures)
        self.assertEqual(fo["quadrant"], ["NEUTRAL", "LONG_BUILDUP"])
        self.assertAlmostEqual(fo["oi_chg1"][1], 0.2)
        self.assertAlmostEqual(fo["rollover"][1], 400 / 1200)
        self.assertEqual(fo["days_to_expiry"][1], 7)
        self.assertFalse(any(fo_features(dates, None)["in_fo"]))


class RegimeTests(unittest.TestCase):
    trend_up = {"close": 110, "sma50": 105, "sma200": 100, "ret20": 0.03}
    trend_down = {"close": 90, "sma50": 95, "sma200": 100, "ret20": -0.05}

    def test_labels(self):
        self.assertEqual(classify_regime(self.trend_up, 0.6, {"level": 13, "chg5": 0.0})["label"], "RISK_ON")
        self.assertEqual(classify_regime(self.trend_down, 0.3, {"level": 24, "chg5": 0.3})["label"], "RISK_OFF")
        self.assertEqual(classify_regime(self.trend_up, 0.45, None)["label"], "NEUTRAL")
        self.assertEqual(classify_regime(None, 0.5, None)["label"], "UNKNOWN")


class SetupTests(unittest.TestCase):
    def test_breakout_52w_needs_volume(self):
        base = fx.trend_bars(100, 260, 0.0, wiggle=0.01)
        last = base[-1][3]
        breakout = (last, last * 1.08, last * 1.01, last * 1.075, 3_000_000, 60.0)
        _, signals = run(fx.make_series(base + [breakout]))
        self.assertIn("BREAKOUT_52W", names(signals))
        quiet = breakout[:4] + (1_000_000, 60.0)
        _, signals = run(fx.make_series(base + [quiet]))
        self.assertNotIn("BREAKOUT_52W", names(signals))

    def test_base_breakout_after_contraction(self):
        trend = fx.trend_bars(50, 120, 0.006, range_pct=0.04)
        top = trend[-1][3]
        base = [(top, top * 1.01, top * 0.99, top * (1.003 if k % 2 else 0.997), 800_000, 40.0) for k in range(25)]
        breakout = (top, top * 1.05, top * 0.995, top * 1.045, 2_000_000, 50.0)
        _, signals = run(fx.make_series(trend + base + [breakout]), names=["BASE_BREAKOUT_VCP"])
        self.assertEqual(names(signals), ["BASE_BREAKOUT_VCP"])
        _, signals = run(fx.make_series(trend + base + [base[-1]]), names=["BASE_BREAKOUT_VCP"])
        self.assertEqual(signals, [])

    def test_pullback_in_uptrend_with_reversal(self):
        up = fx.trend_bars(50, 250, 0.004, range_pct=0.01)
        peak = up[-1][3]
        pull = []
        price = peak
        for _ in range(4):
            close = price * 0.99
            pull.append((price, price * 1.002, close * 0.998, close, 400_000, 40.0))
            price = close
        reversal = (price, price * 1.03, price * 0.998, price * 1.028, 1_200_000, 45.0)
        _, signals = run(fx.make_series(up + pull + [reversal]), names=["PULLBACK_UPTREND"])
        self.assertEqual(names(signals), ["PULLBACK_UPTREND"])

    def fo_for(self, series, oi_change, price_change):
        futures = {}
        oi, price = 1_000_000, series.close[0]
        for i, day in enumerate(series.dates):
            if i == len(series.dates) - 1:
                oi, price = oi * (1 + oi_change), price * (1 + price_change)
            else:
                price = series.close[i]
            futures[day] = {"near_expiry": "2030-01-01", "near_price": price, "near_oi": oi,
                            "next_oi": 0, "total_oi": oi, "volume": 1}
        return fo_features(series.dates, futures)

    def test_long_buildup_and_short_covering(self):
        up = fx.trend_bars(100, 80, 0.002, wiggle=0.005)
        last = up[-1][3]
        series = fx.make_series(up + [(last, last * 1.04, last * 0.995, last * 1.035, 2_500_000, 45.0)])
        _, signals = run(series, fo=self.fo_for(series, 0.10, 0.035), names=["LONG_BUILDUP", "SHORT_COVERING"])
        self.assertEqual(names(signals), ["LONG_BUILDUP"])

        down = fx.trend_bars(100, 80, -0.003, wiggle=0.005)
        last = down[-1][3]
        series = fx.make_series(down + [(last, last * 1.05, last * 0.995, last * 1.045, 2_500_000, 45.0)])
        _, signals = run(series, fo=self.fo_for(series, -0.10, 0.045), names=["LONG_BUILDUP", "SHORT_COVERING"])
        self.assertEqual(names(signals), ["SHORT_COVERING"])
        _, signals = run(series, fo=None, names=["LONG_BUILDUP", "SHORT_COVERING"])
        self.assertEqual(signals, [])

    def test_delivery_accumulation(self):
        bars = fx.trend_bars(100, 60, 0.001, wiggle=0.004, delivery=30.0)
        last = bars[-1][3]
        tight = [(last, last * 1.01, last * 0.99, last * (1.002 if k % 2 else 1.0), 1_000_000, 55.0) for k in range(5)]
        _, signals = run(fx.make_series(bars + tight), names=["DELIVERY_ACCUMULATION"])
        self.assertEqual(names(signals), ["DELIVERY_ACCUMULATION"])
        normal = [bar[:5] + (31.0,) for bar in tight]
        _, signals = run(fx.make_series(bars + normal), names=["DELIVERY_ACCUMULATION"])
        self.assertEqual(signals, [])

    def test_deal_follow_through_ignores_same_day_seller(self):
        bars = fx.trend_bars(500, 70, 0.001, wiggle=0.004)
        series = fx.make_series(bars)
        day = series.dates[-1]
        price = series.close[-1] * 0.99
        buy = {"kind": "BLOCK", "deal_date": day, "symbol": "TEST", "client": "FUND A", "side": "BUY",
               "quantity": 200_000, "price": price}
        _, signals = run(series, deals=[buy], names=["DEAL_FOLLOW_THROUGH"])
        self.assertEqual(names(signals), ["DEAL_FOLLOW_THROUGH"])
        self.assertTrue(signals[0].catalyst["verified"])
        flip = dict(buy, side="SELL")
        _, signals = run(series, deals=[buy, flip], names=["DEAL_FOLLOW_THROUGH"])
        self.assertEqual(signals, [])

    def test_earnings_gap_drift_labels_unverified_gaps(self):
        bars = fx.trend_bars(100, 60, 0.001, wiggle=0.004)
        last = bars[-1][3]
        gap = (last * 1.07, last * 1.10, last * 1.06, last * 1.09, 5_000_000, 50.0)
        hold = (last * 1.09, last * 1.11, last * 1.075, last * 1.10, 2_000_000, 50.0)
        series = fx.make_series(bars + [gap, hold])
        _, signals = run(series, names=["EARNINGS_GAP_DRIFT"])
        self.assertEqual(signals[0].catalyst["type"], "UNEXPLAINED_GAP")
        _, signals = run(series, events={series.dates[-2]: "RESULTS"}, names=["EARNINGS_GAP_DRIFT"])
        self.assertEqual((signals[0].catalyst["type"], signals[0].catalyst["verified"]), ("RESULTS", True))
        filled = hold[:2] + (last * 0.99,) + hold[3:]
        _, signals = run(fx.make_series(bars + [gap, filled]), names=["EARNINGS_GAP_DRIFT"])
        self.assertEqual(signals, [])

    def test_rs_leader_only_in_weak_tape(self):
        series = fx.make_series(fx.trend_bars(100, 120, 0.003, wiggle=0.003))
        _, signals = run(series, bench_return=-0.002, regime="NEUTRAL", names=["RS_LEADER_IN_WEAK_TAPE"])
        self.assertEqual(names(signals), ["RS_LEADER_IN_WEAK_TAPE"])
        _, signals = run(series, bench_return=-0.002, regime="RISK_ON", names=["RS_LEADER_IN_WEAK_TAPE"])
        self.assertEqual(signals, [])

    def test_every_setup_is_registered_with_a_time_stop(self):
        from stockex.signals.setups import DEFAULT_SETUP_PARAMS, SETUP_VERSIONS
        self.assertEqual(set(SETUPS), set(DEFAULT_SETUP_PARAMS["time_stop"]))
        self.assertEqual(set(SETUPS), set(SETUP_VERSIONS))


class RiskPlanTests(unittest.TestCase):
    bar = {"close": 100.0, "high": 101.0, "low": 97.0, "ret1": 0.02, "atr14": 2.0, "value_med20": 2e8}

    def signal(self, entry=101.1, stop=98.0):
        return Signal("BREAKOUT_52W", 1, 0.8, entry, stop, 7, {})

    def test_plan_targets_costs_and_size(self):
        plan = build_plan(self.signal(), self.bar, params={"capital": 1_000_000, "risk_per_trade": 0.01})
        self.assertIsInstance(plan, TradePlan)
        self.assertAlmostEqual(plan.risk_per_share, 3.1)
        self.assertEqual((plan.t1, plan.t2), (round(101.1 + 4.65, 2), round(101.1 + 9.3, 2)))
        cost = 101.1 * 45 / 10_000
        self.assertAlmostEqual(plan.reward_risk_after_costs, round((9.3 - cost) / (3.1 + cost), 3))
        reference = size_cash_trade(101.1, 98.0, 10_000, 200_000, friction_per_share=cost)
        self.assertEqual(plan.shares, reference["shares"])

    def test_tight_stop_is_widened_and_wide_stop_rejected(self):
        plan = build_plan(self.signal(stop=100.5), self.bar)
        self.assertEqual((plan.stop, plan.stop_basis), (99.1, "widened to 1x ATR"))
        self.assertEqual(build_plan(self.signal(stop=90.0), self.bar).code, "STOP_TOO_WIDE")

    def test_hard_blocks(self):
        cases = {
            "RESTRICTED": dict(restrictions=["ASM:LT-1"]),
            "ILLIQUID": dict(bar=dict(self.bar, value_med20=1e6)),
            "PRICE_TOO_LOW": dict(bar=dict(self.bar, close=5.0)),
            "CIRCUIT_LOCKED": dict(bar=dict(self.bar, high=100.0, low=100.0, ret1=0.05)),
            "SIZE_ZERO": dict(params={"capital": 100}),
            "TRADE_FOR_TRADE": dict(bar=dict(self.bar, series="BE")),
        }
        for code, kwargs in cases.items():
            with self.subTest(code=code):
                result = build_plan(self.signal(), kwargs.get("bar", self.bar),
                                    restrictions=kwargs.get("restrictions"), params=kwargs.get("params"))
                self.assertIsInstance(result, Rejection)
                self.assertEqual(result.code, code)

    def test_risk_off_halves_risk_budget(self):
        params = {"capital": 1_000_000, "risk_per_trade": 0.005}
        on = build_plan(self.signal(), self.bar, params=params)
        off = build_plan(self.signal(), self.bar, regime="RISK_OFF", params=params)
        self.assertEqual(on.size_notes, ["Size limited by risk budget"])
        self.assertEqual(off.shares, on.shares // 2)


if __name__ == "__main__":
    unittest.main()
