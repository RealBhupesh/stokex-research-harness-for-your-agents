"""Named, versioned short-term setups evaluated at one bar without lookahead.

Each setup returns a ``Signal`` with a proposed entry trigger, a structural
stop, a time stop and the evidence that fired it, or ``None``. Thresholds are
configurable starting points; the backtester decides which setups have an
edge. A setup's version changes whenever its rule changes, so scorecards
never mix different rules.
"""

from dataclasses import dataclass, field


@dataclass
class SetupContext:
    """Everything a setup may read for one symbol at bar ``i``."""

    fo: dict | None = None
    deals: list = field(default_factory=list)
    events: dict = field(default_factory=dict)
    regime: str = "UNKNOWN"
    params: dict = field(default_factory=dict)


@dataclass
class Signal:
    setup: str
    version: int
    strength: float
    entry: float
    stop: float
    time_stop: int
    evidence: dict
    catalyst: dict | None = None


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _ok(*values) -> bool:
    return all(value is not None for value in values)


def _trigger(high: float) -> float:
    return round(high * 1.001, 2)


def breakout_52w(f, i, ctx, p):
    c = f.columns
    close, high, low = f.series.close[i], f.series.high[i], f.series.low[i]
    prior_high, vol_ratio, rs60 = c["prior_high252"][i], c["vol_ratio"][i], c["rs60"][i]
    if i < p["min_bars_52w"] or not _ok(prior_high, vol_ratio):
        return None
    if close <= prior_high or vol_ratio < p["breakout_volume"] or c["close_position"][i] < 0.6:
        return None
    if rs60 is not None and rs60 <= 0:
        return None
    deliv_ratio = c["deliv_ratio"][i]
    if deliv_ratio is not None and deliv_ratio < 1.0:
        return None
    strength = 0.4 * _clip(vol_ratio / 4) + 0.3 * c["close_position"][i] + 0.3 * _clip((rs60 or 0) / 0.2)
    return Signal("BREAKOUT_52W", 1, strength, _trigger(high), low, p["time_stop"]["BREAKOUT_52W"], {
        "close": close, "prior_52w_high": prior_high, "volume_ratio": vol_ratio,
        "delivery_ratio": deliv_ratio, "rs60": rs60,
    })


def base_breakout_vcp(f, i, ctx, p):
    c = f.columns
    close, high = f.series.close[i], f.series.high[i]
    base_range, contraction = c["base_range20"][i], c["atr_contraction"][i - 1] if i else None
    prior_high, vol_ratio, sma50 = c["prior_high20"][i], c["vol_ratio"][i], c["sma50"][i]
    if not _ok(base_range, contraction, prior_high, vol_ratio, sma50, c["prior_low10"][i]):
        return None
    if base_range > p["vcp_max_base_range"] or contraction > p["vcp_max_contraction"]:
        return None
    if close <= prior_high or vol_ratio < p["vcp_volume"] or close < sma50:
        return None
    strength = 0.4 * _clip(vol_ratio / 3) + 0.3 * _clip(1 - base_range / p["vcp_max_base_range"]) \
        + 0.3 * _clip(1 - contraction)
    return Signal("BASE_BREAKOUT_VCP", 1, strength, _trigger(high), c["prior_low10"][i],
                  p["time_stop"]["BASE_BREAKOUT_VCP"], {
                      "base_range20": base_range, "atr_contraction": contraction,
                      "base_high": prior_high, "volume_ratio": vol_ratio,
                  })


def pullback_uptrend(f, i, ctx, p):
    c, s = f.columns, f.series
    sma20, sma50, sma200 = c["sma20"][i], c["sma50"][i], c["sma200"][i]
    if i < 5 or not _ok(sma20, sma50, sma200, c["ret60"][i], c["vol_med20"][i]):
        return None
    if not (sma50 > sma200 and s.close[i] > sma50 and c["ret60"][i] > 0):
        return None
    recent_low = min(s.low[i - 4:i + 1])
    touched = recent_low <= sma20 * (1 + p["pullback_touch"]) or recent_low <= sma50 * (1 + p["pullback_touch"])
    quiet = sum(s.volume[i - 3:i]) / 3 < c["vol_med20"][i]
    reversal = s.close[i] > s.open[i] and s.close[i] > s.high[i - 1]
    if not (touched and quiet and reversal):
        return None
    trend = (sma50 / sma200 - 1)
    strength = 0.5 * _clip(trend / 0.15) + 0.5 * c["close_position"][i]
    return Signal("PULLBACK_UPTREND", 1, strength, _trigger(s.high[i]), recent_low,
                  p["time_stop"]["PULLBACK_UPTREND"], {
                      "sma20": sma20, "sma50": sma50, "sma200": sma200, "pullback_low": recent_low,
                  })


def long_buildup(f, i, ctx, p):
    fo = ctx.fo
    if not fo or not fo["in_fo"][i]:
        return None
    c, s = f.columns, f.series
    ret1, oi_chg1, vol_ratio, sma20 = c["ret1"][i], fo["oi_chg1"][i], c["vol_ratio"][i], c["sma20"][i]
    if not _ok(ret1, oi_chg1, vol_ratio, sma20):
        return None
    if ret1 < p["buildup_price"] or oi_chg1 < p["buildup_oi"] or vol_ratio < 1.5 or s.close[i] < sma20:
        return None
    strength = 0.4 * _clip(oi_chg1 / 0.15) + 0.3 * _clip(ret1 / 0.05) + 0.3 * _clip(vol_ratio / 3)
    return Signal("LONG_BUILDUP", 1, strength, _trigger(s.high[i]), s.low[i], p["time_stop"]["LONG_BUILDUP"], {
        "price_change": ret1, "oi_change": oi_chg1, "oi_change_5d": fo["oi_chg5"][i],
        "volume_ratio": vol_ratio, "quadrant": fo["quadrant"][i],
    })


def short_covering(f, i, ctx, p):
    fo = ctx.fo
    if not fo or not fo["in_fo"][i]:
        return None
    c, s = f.columns, f.series
    ret1, oi_chg1, ret20_prior = c["ret1"][i], fo["oi_chg1"][i], c["ret20"][i - 1] if i else None
    if not _ok(ret1, oi_chg1, ret20_prior):
        return None
    if ret1 < p["covering_price"] or oi_chg1 > -p["covering_oi"] or ret20_prior > 0:
        return None
    strength = 0.5 * _clip(-oi_chg1 / 0.15) + 0.5 * _clip(ret1 / 0.06)
    return Signal("SHORT_COVERING", 1, strength, _trigger(s.high[i]), s.low[i], p["time_stop"]["SHORT_COVERING"], {
        "price_change": ret1, "oi_change": oi_chg1, "prior_20d_return": ret20_prior,
    })


def delivery_accumulation(f, i, ctx, p):
    c, s = f.columns, f.series
    if i < 25 or not _ok(c["sma50"][i], c["deliv_avg20"][i - 4]):
        return None
    baseline = c["deliv_avg20"][i - 4]
    window = s.delivery_pct[i - 4:i + 1]
    if any(value is None for value in window) or not baseline:
        return None
    ratio = sum(window) / len(window) / baseline
    tight = (max(s.high[i - 4:i + 1]) - min(s.low[i - 4:i + 1])) / s.close[i]
    if ratio < p["accumulation_delivery"] or tight > p["accumulation_range"] or s.close[i] < c["sma50"][i]:
        return None
    strength = 0.6 * _clip((ratio - 1) / 0.8) + 0.4 * _clip(1 - tight / p["accumulation_range"])
    return Signal("DELIVERY_ACCUMULATION", 1, strength, _trigger(max(s.high[i - 4:i + 1])),
                  min(s.low[i - 4:i + 1]), p["time_stop"]["DELIVERY_ACCUMULATION"], {
                      "delivery_vs_baseline": ratio, "five_day_range": tight,
                      "delivery_pct_5d": window,
                  })


def deal_follow_through(f, i, ctx, p):
    if not ctx.deals:
        return None
    s, c = f.series, f.columns
    window_dates = set(s.dates[max(0, i - p["deal_lookback"] + 1):i + 1])
    buys = [d for d in ctx.deals if d["deal_date"] in window_dates and d["side"] == "BUY"]
    sellers = {(d["deal_date"], d["client"]) for d in ctx.deals if d["side"] == "SELL"}
    buys = [d for d in buys if (d["deal_date"], d["client"]) not in sellers]
    value_med = c["value_med20"][i]
    buys = [d for d in buys if d["quantity"] * d["price"] >= p["deal_min_value"]]
    if not buys or not value_med:
        return None
    biggest = max(buys, key=lambda d: d["quantity"] * d["price"])
    if s.close[i] < biggest["price"]:
        return None
    atr14 = c["atr14"][i] or 0
    size_vs_liquidity = biggest["quantity"] * biggest["price"] / value_med
    strength = 0.6 * _clip(size_vs_liquidity / 2) + 0.4 * _clip((s.close[i] / biggest["price"] - 1) / 0.05 + 0.5)
    return Signal("DEAL_FOLLOW_THROUGH", 1, strength, _trigger(s.high[i]),
                  min(biggest["price"] - 0.5 * atr14, s.low[i]), p["time_stop"]["DEAL_FOLLOW_THROUGH"], {
                      "deal_kind": biggest["kind"], "client": biggest["client"], "deal_date": biggest["deal_date"],
                      "deal_price": biggest["price"], "deal_value": biggest["quantity"] * biggest["price"],
                      "deal_vs_median_daily_value": size_vs_liquidity,
                  }, catalyst={"type": f"{biggest['kind']}_DEAL", "date": biggest["deal_date"],
                               "source": "NSE bulk/block deal file", "verified": True})


def earnings_gap_drift(f, i, ctx, p):
    if i < 2:
        return None
    s, c = f.series, f.columns
    g = i - 1
    gap, vol_ratio = c["gap_pct"][g], c["vol_ratio"][g]
    if not _ok(gap, vol_ratio) or gap < p["gap_min"] or vol_ratio < p["gap_volume"]:
        return None
    gap_floor = s.close[g - 1]
    if s.low[i] <= gap_floor or s.close[i] < s.open[g]:
        return None
    event = ctx.events.get(s.dates[g]) or ctx.events.get(s.dates[g - 1])
    catalyst = (
        {"type": event, "date": s.dates[g], "source": "user events file", "verified": True}
        if event else
        {"type": "UNEXPLAINED_GAP", "date": s.dates[g], "source": None, "verified": False}
    )
    strength = 0.4 * _clip(gap / 0.1) + 0.3 * _clip(vol_ratio / 5) + 0.3 * (1.0 if event else 0.3)
    return Signal("EARNINGS_GAP_DRIFT", 1, strength, _trigger(max(s.high[g], s.high[i])),
                  min(s.low[g], s.low[i]), p["time_stop"]["EARNINGS_GAP_DRIFT"], {
                      "gap_date": s.dates[g], "gap_pct": gap, "gap_volume_ratio": vol_ratio,
                      "gap_floor": gap_floor,
                  }, catalyst=catalyst)


def rs_leader_in_weak_tape(f, i, ctx, p):
    c, s = f.columns, f.series
    bench20 = c["bench_ret20"][i]
    if ctx.regime not in {"RISK_OFF", "NEUTRAL"} or not _ok(bench20, c["rs20"][i], c["rs60"][i]):
        return None
    if bench20 >= 0 or c["rs20"][i] < p["rs_min20"] or c["rs60"][i] < p["rs_min60"]:
        return None
    prior_high, sma50, low10 = c["prior_high50"][i], c["sma50"][i], c["prior_low10"][i]
    if not _ok(prior_high, sma50, low10) or s.close[i] < sma50 or s.close[i] < prior_high * 0.95:
        return None
    strength = 0.5 * _clip(c["rs20"][i] / 0.2) + 0.5 * _clip(c["rs60"][i] / 0.3)
    return Signal("RS_LEADER_IN_WEAK_TAPE", 1, strength, _trigger(max(s.high[i], prior_high)), low10,
                  p["time_stop"]["RS_LEADER_IN_WEAK_TAPE"], {
                      "rs20": c["rs20"][i], "rs60": c["rs60"][i], "nifty_ret20": bench20,
                  })


SETUPS = {
    "BREAKOUT_52W": breakout_52w,
    "BASE_BREAKOUT_VCP": base_breakout_vcp,
    "PULLBACK_UPTREND": pullback_uptrend,
    "LONG_BUILDUP": long_buildup,
    "SHORT_COVERING": short_covering,
    "DELIVERY_ACCUMULATION": delivery_accumulation,
    "DEAL_FOLLOW_THROUGH": deal_follow_through,
    "EARNINGS_GAP_DRIFT": earnings_gap_drift,
    "RS_LEADER_IN_WEAK_TAPE": rs_leader_in_weak_tape,
}

DEFAULT_SETUP_PARAMS = {
    "min_bars_52w": 200,
    "breakout_volume": 2.0,
    "vcp_max_base_range": 0.12,
    "vcp_max_contraction": 0.8,
    "vcp_volume": 1.5,
    "pullback_touch": 0.015,
    "buildup_price": 0.02,
    "buildup_oi": 0.05,
    "covering_price": 0.03,
    "covering_oi": 0.05,
    "accumulation_delivery": 1.3,
    "accumulation_range": 0.06,
    "deal_lookback": 3,
    "deal_min_value": 5e7,
    "gap_min": 0.04,
    "gap_volume": 3.0,
    "rs_min20": 0.08,
    "rs_min60": 0.12,
    "time_stop": {
        "BREAKOUT_52W": 7, "BASE_BREAKOUT_VCP": 8, "PULLBACK_UPTREND": 8, "LONG_BUILDUP": 5,
        "SHORT_COVERING": 3, "DELIVERY_ACCUMULATION": 10, "DEAL_FOLLOW_THROUGH": 7,
        "EARNINGS_GAP_DRIFT": 10, "RS_LEADER_IN_WEAK_TAPE": 10,
    },
}


# Bump a setup's version whenever its rule or default thresholds change.
SETUP_VERSIONS = {name: 1 for name in SETUPS}


def evaluate_setups(f, i, ctx: SetupContext, names=None) -> list[Signal]:
    params = {**DEFAULT_SETUP_PARAMS, **ctx.params}
    params["time_stop"] = {**DEFAULT_SETUP_PARAMS["time_stop"], **ctx.params.get("time_stop", {})}
    signals = []
    for name in names or SETUPS:
        signal = SETUPS[name](f, i, ctx, params)
        if signal is not None:
            signal.version = SETUP_VERSIONS[name]
            signal.strength = round(_clip(signal.strength), 4)
            signals.append(signal)
    return signals
