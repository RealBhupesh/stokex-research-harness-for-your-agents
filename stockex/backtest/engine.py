"""Walk-forward backtest of the scanner on imported end-of-day data.

For each trading day D the scanner sees bars up to D only. An order is valid
for the next session: it fills at the open if the open gaps through the
trigger, at the trigger if the day's high reaches it, and otherwise expires.
Exits are checked conservatively on daily bars: a gap below the stop exits at
the open, and when a bar touches both the stop and a target, the stop wins.
"""

from collections import defaultdict
from datetime import date, timedelta

from ..jev.calibration import evaluate_jev
from ..jev.candidates import CANDIDATE_QUESTION_BANK_VERSION, JudgeBudget, candidate_state, judge_state
from ..market.queries import index_closes, restrictions_on, trading_dates
from ..signals.regime import BENCHMARK_INDEX
from ..signals.risk_plan import DEFAULT_RISK_PARAMS
from ..signals.meta_model import MODEL_FEATURE_VERSION, LogisticModel, WalkForwardModel, feature_vector
from ..signals.scan import evaluate_day, prepare_universe
from ..signals.setups import SETUPS


def simulate_trade(series, signal_index: int, plan: dict, *, cost_bps: float) -> dict | None:
    """Simulate one planned trade from the session after ``signal_index``."""
    fill_index = signal_index + 1
    if fill_index >= len(series):
        return None
    entry, stop, t1, t2 = plan["entry"], plan["stop"], plan["t1"], plan["t2"]
    day_open, day_high = series.open[fill_index], series.high[fill_index]
    if day_high == series.low[fill_index] and day_open >= entry:
        # Locked at the upper circuit all day: buyers queue but rarely fill.
        return {"filled": False, "signal_date": series.dates[signal_index], "reason": "CIRCUIT_LOCKED"}
    if day_open >= entry:
        fill = day_open
    elif day_high >= entry:
        fill = entry
    else:
        return {"filled": False, "signal_date": series.dates[signal_index]}
    initial_risk = fill - stop
    if initial_risk <= 0:
        return {"filled": False, "signal_date": series.dates[signal_index], "reason": "GAP_ABOVE_TARGET_RISK"}

    remaining, realised, legs = 1.0, 0.0, []
    current_stop, t1_hit = stop, False
    exit_reason, exit_index = None, None

    def close_leg(fraction, price, reason, index):
        nonlocal remaining, realised
        realised += fraction * (price - fill)
        remaining -= fraction
        legs.append({"date": series.dates[index], "fraction": fraction, "price": round(price, 4), "reason": reason})

    for k in range(fill_index, len(series)):
        o, h, l, c = series.open[k], series.high[k], series.low[k], series.close[k]
        held = k - fill_index + 1
        if k > fill_index and h == l and l <= current_stop:
            continue  # locked at the lower circuit: no sellers fill today; exit at the next open
        if k > fill_index and o <= current_stop:
            close_leg(remaining, o, "GAP_STOP", k)
        elif l <= current_stop:
            close_leg(remaining, current_stop, "STOP" if not t1_hit else "TRAIL_STOP", k)
        else:
            # A gap above a target fills at the open (or at our fill on entry day), never below it.
            reference = o if k > fill_index else fill
            if not t1_hit and h >= t1:
                close_leg(0.5, max(t1, reference), "T1", k)
                t1_hit, current_stop = True, max(current_stop, fill)
            if remaining > 0 and h >= t2:
                close_leg(remaining, max(t2, reference), "T2", k)
            elif remaining > 0 and held >= plan["time_stop_sessions"]:
                close_leg(remaining, c, "TIME_STOP", k)
            elif remaining > 0 and t1_hit and k >= 1:
                current_stop = max(current_stop, min(series.low[k - 1], l))
        if remaining <= 1e-9:
            exit_reason, exit_index = legs[-1]["reason"], k
            break
    if exit_reason is None:
        close_leg(remaining, series.close[-1], "END_OF_DATA", len(series) - 1)
        exit_reason, exit_index = "END_OF_DATA", len(series) - 1
    if plan.get("round_trip_cost_per_share") and plan.get("entry"):
        cost = fill * plan["round_trip_cost_per_share"] / plan["entry"]
    else:
        cost = fill * cost_bps / 10_000
    net = realised - cost
    return {
        "filled": True,
        "signal_date": series.dates[signal_index],
        "entry_date": series.dates[fill_index],
        "exit_date": series.dates[exit_index],
        "fill": round(fill, 4),
        "initial_stop": stop,
        "exit_reason": exit_reason,
        "legs": legs,
        "return_pct": net / fill,
        "r_multiple": net / initial_risk,
        "sessions_held": exit_index - fill_index + 1,
    }


def _stats(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0, "hit_rate": None, "expectancy_r": None, "avg_return_pct": None,
                "profit_factor": None, "avg_sessions_held": None, "worst_r": None, "max_losing_streak": 0,
                "gap_stop_rate": None, "avg_loss_beyond_stop_r": None}
    rs = [t["r_multiple"] for t in trades]
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    streak = worst_streak = 0
    for r in rs:
        streak = streak + 1 if r <= 0 else 0
        worst_streak = max(worst_streak, streak)
    return {
        "trades": len(trades),
        "hit_rate": round(sum(r > 0 for r in rs) / len(rs), 4),
        "expectancy_r": round(sum(rs) / len(rs), 4),
        "avg_return_pct": round(sum(t["return_pct"] for t in trades) / len(trades), 5),
        "profit_factor": round(gains / losses, 3) if losses else None,
        "avg_sessions_held": round(sum(t["sessions_held"] for t in trades) / len(trades), 2),
        "worst_r": round(min(rs), 3),
        "max_losing_streak": worst_streak,
        "gap_stop_rate": round(sum(t["exit_reason"] == "GAP_STOP" for t in trades) / len(trades), 4),
        "avg_loss_beyond_stop_r": round(
            sum(-1 - r for r in rs if r < -1.05) / max(1, sum(1 for r in rs if r < -1.05)), 4),
    }


EXIT_GRACE_DAYS = 30


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def run_backtest(connection, start: str, end: str, *, setups=None, setup_params=None, risk_params=None,
                 events=None, capital: float = 1_000_000, max_positions: int = 5, progress=None,
                 jev_client=None, jev_cache=None, jev_max_calls: int | None = 2000) -> dict:
    """Walk forward over [start, end]. Returns per-setup stats, trades and a portfolio equity curve.

    Setup statistics come from every signal simulated independently (the
    signal study), so capacity limits do not hide how a setup behaves. The
    portfolio simulation then takes the highest-ranked signals up to
    ``max_positions`` to show a realistic equity curve.

    With ``jev_client``, every filled trade is also judged by Jev from an
    anonymized signal-day state, and the result carries a calibration report
    that decides whether Jev may influence future scans.
    """
    budget = JudgeBudget(jev_max_calls)
    setup_names = list(SETUPS)
    model = WalkForwardModel(setup_names)
    risk = {**DEFAULT_RISK_PARAMS, **(risk_params or {}), "capital": capital}
    cost_bps = risk["round_trip_cost_bps"]
    # Signals only use bars up to each day (features are causal), but open
    # trades near ``end`` need later bars to reach their exits.
    later = trading_dates(connection, _shift(end, 1), _shift(end, EXIT_GRACE_DAYS))
    data_through = later[-1] if later else end
    universe = prepare_universe(connection, data_through, start=start, events=events)
    days = trading_dates(connection, start, end)
    signal_trades, daily_candidates = [], {}
    for n, day in enumerate(days):
        model.maybe_refit(day, signal_trades)
        restrictions = restrictions_on(connection, day, through=_shift(day, 4))
        result = evaluate_day(universe, day, setups=setups, setup_params=setup_params,
                              risk_params=risk, restrictions=restrictions)
        daily_candidates[day] = (result["regime"]["label"], result["candidates"])
        for candidate in result["candidates"]:
            f = universe.features[candidate["symbol"]]
            trade = simulate_trade(f.series, f.index_of(day), candidate["plan"], cost_bps=cost_bps)
            if trade and trade["filled"]:
                trade.update(symbol=candidate["symbol"], setup=candidate["setup"],
                             regime=result["regime"]["label"], score=candidate["score"]["total"],
                             shares=candidate["plan"]["shares"],
                             t1_hit=any(leg["reason"] in {"T1", "T2"} for leg in trade["legs"]))
                state = candidate_state(candidate, f.at(f.index_of(day)), result["regime"])
                trade["model_features"] = feature_vector(state, setup_names)
                trade["model_p"] = model.predict(trade["model_features"])
                if jev_client is not None:
                    judgment = judge_state(state, jev_client, jev_cache, budget)
                    trade["jev"] = judgment
                    trade["jev_p"] = judgment.get("follow_through")
                signal_trades.append(trade)
        if progress:
            progress(n + 1, len(days))

    by_setup: dict = defaultdict(list)
    by_setup_regime: dict = defaultdict(lambda: defaultdict(list))
    for trade in signal_trades:
        by_setup[trade["setup"]].append(trade)
        by_setup_regime[trade["setup"]][trade["regime"]].append(trade)
    setups_report = {
        name: {"overall": _stats(trades),
               "by_regime": {regime: _stats(items) for regime, items in sorted(by_setup_regime[name].items())}}
        for name, trades in sorted(by_setup.items())
    }
    portfolio = _portfolio(universe, days, daily_candidates, signal_trades, capital, max_positions,
                           index_closes(connection, BENCHMARK_INDEX, end), risk["max_per_sector"])
    for trade in signal_trades:
        trade["exit_after_period"] = trade["exit_date"] > end
    t1_base_rates = {
        name: round(sum(t["t1_hit"] for t in trades) / len(trades), 4) for name, trades in sorted(by_setup.items())
    }
    model_report = {
        **evaluate_jev(signal_trades, key="model_p"),
        "feature_version": MODEL_FEATURE_VERSION,
        "walk_forward_fits": model.fits,
        "coefficients": None,
    }
    if len(signal_trades) >= model.min_train and len({t["t1_hit"] for t in signal_trades}) == 2:
        final = LogisticModel.fit([t["model_features"] for t in signal_trades],
                                  [int(t["t1_hit"]) for t in signal_trades])
        model_report["coefficients"] = final.to_dict()
    for trade in signal_trades:
        trade.pop("model_features", None)
    jev = None
    if jev_client is not None:
        jev = {
            **evaluate_jev(signal_trades),
            "question_bank_version": CANDIDATE_QUESTION_BANK_VERSION,
            "model_requested": getattr(jev_client, "model", "unknown"),
            "models_returned": sorted({t["jev"]["model"] for t in signal_trades
                                       if t.get("jev", {}).get("status") == "JUDGED"}),
            "usage": budget.report(),
        }
    return {
        "period": {"from": start, "to": end, "trading_days": len(days), "data_through": data_through},
        "capital": capital,
        "max_positions": max_positions,
        "risk_params": {k: v for k, v in risk.items() if not isinstance(v, tuple)},
        "setup_params": setup_params or {},
        "overall": _stats(signal_trades),
        "setups": setups_report,
        "t1_base_rates": t1_base_rates,
        "jev": jev,
        "model": model_report,
        "portfolio": portfolio,
        "trades": signal_trades,
        "notes": [
            "Daily bars cannot show intraday order: a bar touching stop and target counts as a stop.",
            "Costs use a flat round-trip estimate; taxes and impact in stressed markets are not modelled.",
            "Results are in-sample for any parameter tuned on this period.",
        ],
    }


def _portfolio(universe, days, daily_candidates, signal_trades, capital, max_positions, benchmark,
               max_per_sector: int = 0) -> dict:
    trades_by_key = {(t["symbol"], t["signal_date"]): t for t in signal_trades}
    open_positions: list[dict] = []
    taken, cash, equity_curve = [], capital, []
    for day in days:
        # Close positions whose exit date has arrived.
        still_open = []
        for position in open_positions:
            if position["exit_date"] <= day:
                cash += position["shares"] * position["fill"] * (1 + position["return_pct"])
            else:
                still_open.append(position)
        open_positions = still_open
        regime, candidates = daily_candidates[day]
        busy = {p["symbol"] for p in open_positions}
        for candidate in candidates:
            if len(open_positions) >= max_positions:
                break
            trade = trades_by_key.get((candidate["symbol"], day))
            shares = candidate["plan"]["shares"]
            if not trade or candidate["symbol"] in busy or not shares:
                continue
            sector = candidate.get("sector")
            if max_per_sector and sector is not None and sum(
                    1 for p in open_positions if p.get("sector") == sector) >= max_per_sector:
                continue
            cost = shares * trade["fill"]
            if cost > cash:
                continue
            cash -= cost
            position = dict(trade, shares=shares, sector=sector)
            open_positions.append(position)
            taken.append(position)
            busy.add(candidate["symbol"])
        marked = cash
        for position in open_positions:
            f = universe.features[position["symbol"]]
            i = f.index_of(day)
            price = f.series.close[i] if i is not None and day >= position["entry_date"] else position["fill"]
            marked += position["shares"] * price
        equity_curve.append({"date": day, "equity": round(marked, 2)})
    for position in open_positions:
        cash += position["shares"] * position["fill"] * (1 + position["return_pct"])
    final = cash if not equity_curve else equity_curve[-1]["equity"]
    peak, max_drawdown = capital, 0.0
    for point in equity_curve:
        peak = max(peak, point["equity"])
        max_drawdown = min(max_drawdown, point["equity"] / peak - 1)
    bench_days = [day for day in days if day in benchmark]
    bench_return = (benchmark[bench_days[-1]] / benchmark[bench_days[0]] - 1) if len(bench_days) >= 2 else None
    return {
        "trades_taken": len(taken),
        "final_equity": round(final, 2),
        "total_return": round(final / capital - 1, 5),
        "max_drawdown": round(max_drawdown, 5),
        "benchmark": BENCHMARK_INDEX,
        "benchmark_return": None if bench_return is None else round(bench_return, 5),
        "stats": _stats(taken),
        "equity_curve": equity_curve,
    }
