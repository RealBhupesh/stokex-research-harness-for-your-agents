"""Scan the liquid universe on one date and rank setups with hard risk plans."""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
import math

from ..jev.candidates import CANDIDATE_QUESTION_BANK_VERSION, JudgeBudget, candidate_state, judge_state
from ..market.queries import (
    deals_between, futures_history, index_closes, load_histories, option_chain, restrictions_on,
)
from .fo import fo_features, option_context
from .indicators import Features, compute_features
from .regime import BENCHMARK_INDEX, VIX_INDEX, benchmark_trend, classify_regime, vix_state
from .risk_plan import DEFAULT_RISK_PARAMS, Rejection, build_plan
from .setups import SETUP_VERSIONS, SETUPS, SetupContext, evaluate_setups


MIN_BARS = 60
SCORE_WEIGHTS = {"strength": 0.35, "edge": 0.25, "reward_risk": 0.15, "liquidity": 0.15, "catalyst": 0.10}
MIN_PROVEN_TRADES = 30
JEV_WEIGHT = 0.20


@dataclass
class Universe:
    features: dict
    fo: dict
    deals: dict
    events: dict
    trend: dict
    vix: dict
    notes: list = field(default_factory=list)


def _shift(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def prepare_universe(connection, as_of: str, *, start: str | None = None, lookback_days: int = 420,
                     events: dict | None = None, symbols: list[str] | None = None) -> Universe:
    """Load and featurise every symbol with data up to ``as_of``."""
    load_from = _shift(start or as_of, -lookback_days)
    benchmark = index_closes(connection, BENCHMARK_INDEX, as_of)
    notes = [] if benchmark else [f"No {BENCHMARK_INDEX} index data: relative strength and regime are unavailable"]
    histories = load_histories(connection, as_of, start=load_from, symbols=symbols)
    features = {symbol: compute_features(series, benchmark or None) for symbol, series in histories.items()}
    futures = futures_history(connection, as_of, start=load_from, symbols=symbols)
    fo = {symbol: fo_features(f.series.dates, futures.get(symbol)) for symbol, f in features.items()}
    deals: dict = {}
    for deal in deals_between(connection, load_from, as_of):
        deals.setdefault(deal["symbol"], []).append(deal)
    vix = index_closes(connection, VIX_INDEX, as_of)
    return Universe(
        features=features, fo=fo, deals=deals, events=events or {},
        trend=benchmark_trend(benchmark) if benchmark else {},
        vix=vix_state(vix) if vix else {}, notes=notes,
    )


def breadth_on(universe: Universe, day: str) -> float | None:
    above = total = 0
    for f in universe.features.values():
        i = f.index_of(day)
        if i is None:
            continue
        sma50 = f.columns["sma50"][i]
        if sma50 is None:
            continue
        total += 1
        above += f.series.close[i] > sma50
    return above / total if total >= 10 else None


def regime_on(universe: Universe, day: str) -> dict:
    return classify_regime(universe.trend.get(day), breadth_on(universe, day), universe.vix.get(day))


def _track_record(scorecard: dict | None, setup: str, regime: str) -> dict:
    if not scorecard:
        return {"status": "NO_SCORECARD"}
    entry = scorecard.get("setups", {}).get(setup)
    if not entry or entry.get("version") != SETUP_VERSIONS[setup]:
        return {"status": "UNPROVEN", "reason": "Setup not in scorecard or version changed"}
    record = entry.get("by_regime", {}).get(regime) or entry.get("overall", {})
    trades, expectancy = record.get("trades", 0), record.get("expectancy_r")
    status = "PROVEN" if trades >= MIN_PROVEN_TRADES and expectancy is not None and expectancy > 0 else "UNPROVEN"
    return {"status": status, "trades": trades, "hit_rate": record.get("hit_rate"),
            "expectancy_r": expectancy, "basis": regime if regime in entry.get("by_regime", {}) else "overall"}


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score(signal, plan, bar, track: dict, min_traded_value: float) -> dict:
    expectancy = track.get("expectancy_r")
    edge = 0.5 if track["status"] == "NO_SCORECARD" else (
        _clip((expectancy + 0.5) / 1.0) if track["status"] == "PROVEN" and expectancy is not None else 0.0
    )
    catalyst = 0.3 if not signal.catalyst else (1.0 if signal.catalyst.get("verified") else 0.5)
    components = {
        "strength": signal.strength,
        "edge": edge,
        "reward_risk": _clip((plan.reward_risk_after_costs - 2) / 2),
        "liquidity": _clip(math.log10(max(bar["value_med20"], 1) / min_traded_value) / 2),
        "catalyst": catalyst,
    }
    total = sum(SCORE_WEIGHTS[name] * value for name, value in components.items())
    return {"total": round(total, 4), "components": {k: round(v, 4) for k, v in components.items()}}


def evaluate_day(universe: Universe, day: str, *, setups=None, setup_params=None, risk_params=None,
                 scorecard=None, restrictions: dict | None = None) -> dict:
    """Candidates and rejections for one trading day using bars up to ``day`` only."""
    regime = regime_on(universe, day)
    risk = {**DEFAULT_RISK_PARAMS, **(risk_params or {})}
    restrictions = restrictions or {}
    candidates, rejected = [], []
    for symbol, f in sorted(universe.features.items()):
        i = f.index_of(day)
        if i is None or i < MIN_BARS:
            continue
        fo = universe.fo.get(symbol)
        context = SetupContext(
            fo=fo, deals=universe.deals.get(symbol, []),
            events=universe.events.get(symbol, {}), regime=regime["label"], params=setup_params or {},
        )
        signals = evaluate_setups(f, i, context, setups)
        if not signals:
            continue
        bar = f.at(i)
        bar.update(close=f.series.close[i], high=f.series.high[i], low=f.series.low[i],
                   series=f.series.series[i])
        if regime["label"] == "RISK_OFF" and not ((bar["rs20"] or 0) > 0 and (bar["rs60"] or 0) > 0):
            rejected.append({"symbol": symbol, "setups": [s.setup for s in signals], "code": "WEAK_RS_IN_RISK_OFF",
                             "message": "RISK_OFF regime allows only relative-strength leaders"})
            continue
        best = None
        for signal in signals:
            plan = build_plan(signal, bar, restrictions=restrictions.get(symbol, []),
                              regime=regime["label"], params=risk)
            if isinstance(plan, Rejection):
                rejected.append({"symbol": symbol, "setups": [signal.setup], "code": plan.code, "message": plan.message})
                continue
            track = _track_record(scorecard, signal.setup, regime["label"])
            score = _score(signal, plan, bar, track, risk["min_traded_value"])
            option = (track["status"] == "PROVEN", score["total"])
            if best is None or option > best[0]:
                best = (option, signal, plan, track, score)
        if best is None:
            continue
        _, signal, plan, track, score = best
        candidates.append({
            "symbol": symbol,
            "date": day,
            "setup": signal.setup,
            "setup_version": signal.version,
            "other_setups": sorted(s.setup for s in signals if s.setup != signal.setup),
            "close": f.series.close[i],
            "strength": signal.strength,
            "catalyst": signal.catalyst,
            "evidence": _rounded(signal.evidence),
            "fo": _fo_snapshot(fo, i),
            "liquidity": {"median_traded_value_20d": bar["value_med20"], "atr_pct": bar["atr_pct"]},
            "plan": asdict(plan),
            "track_record": track,
            "score": score,
            "series": f.series.series[i],
        })
    candidates.sort(key=lambda c: (c["track_record"]["status"] == "PROVEN", c["score"]["total"]), reverse=True)
    for rank, candidate in enumerate(candidates, 1):
        candidate["rank"] = rank
    return {"regime": regime, "candidates": candidates, "rejected": rejected}


def _fo_snapshot(fo: dict | None, i: int) -> dict | None:
    if not fo or not fo["in_fo"][i]:
        return None
    return _rounded({key: fo[key][i] for key in ("quadrant", "oi_chg1", "oi_chg5", "rollover", "days_to_expiry")})


def _rounded(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def jev_proof(scorecard: dict | None, client) -> dict:
    """Whether a scorecard lets Jev influence this scan, and why."""
    section = (scorecard or {}).get("jev")
    if not section:
        return {"status": "NO_SCORECARD", "reason": "No Jev calibration in the scorecard (run `backtest --jev`)"}
    model = getattr(client, "model", "unknown")
    if section.get("question_bank_version") != CANDIDATE_QUESTION_BANK_VERSION:
        return {"status": "UNPROVEN", "reason": "Scorecard used a different Jev question bank"}
    if section.get("model_requested") != model:
        return {"status": "UNPROVEN", "reason": f"Scorecard measured Jev model {section.get('model_requested')}, not {model}"}
    if section.get("status") != "PROVEN":
        return {"status": "UNPROVEN", "reason": "; ".join(section.get("reasons", [])) or "Not proven"}
    return {"status": "PROVEN", "reason": f"Brier skill {section['brier_skill']}, AUC {section['auc']}",
            "base_rates": section.get("base_rates", {})}


def apply_jev(universe: Universe, day: str, result: dict, client, *, cache=None, scorecard=None,
              limit: int | None = None) -> dict:
    """Judge candidates with Jev; filter and re-rank only when the scorecard proves Jev's edge."""
    proof = jev_proof(scorecard, client)
    budget = JudgeBudget(None)
    candidates = result["candidates"] if limit is None else result["candidates"][:limit]
    kept, filtered = [], []
    for candidate in candidates:
        f = universe.features[candidate["symbol"]]
        state = candidate_state(candidate, f.at(f.index_of(day)), result["regime"])
        judgment = judge_state(state, client, cache, budget)
        judgment["proof"] = proof["status"]
        candidate["jev"] = judgment
        base_rate = proof.get("base_rates", {}).get(candidate["setup"])
        if proof["status"] != "PROVEN" or judgment["status"] != "JUDGED" or base_rate is None:
            judgment["effect"] = "NONE"
            kept.append(candidate)
            continue
        p = judgment["follow_through"]
        judgment["base_rate"] = base_rate
        if p < base_rate:
            judgment["effect"] = "FILTERED"
            filtered.append({"symbol": candidate["symbol"], "setups": [candidate["setup"]], "code": "JEV_FILTERED",
                             "message": f"Jev follow-through {p:.2f} below the setup base rate {base_rate:.2f}"})
            continue
        edge = _clip((p - base_rate) / 0.3 + 0.5)
        score = candidate["score"]
        score["components"]["jev_edge"] = round(edge, 4)
        score["total"] = round((1 - JEV_WEIGHT) * score["total"] + JEV_WEIGHT * edge, 4)
        judgment["effect"] = "RANKED"
        kept.append(candidate)
    kept += [] if limit is None else result["candidates"][limit:]
    kept.sort(key=lambda c: (c["track_record"]["status"] == "PROVEN", c["score"]["total"]), reverse=True)
    for rank, candidate in enumerate(kept, 1):
        candidate["rank"] = rank
    result["candidates"] = kept
    result["rejected"] = result["rejected"] + filtered
    return {"proof": proof, "usage": budget.report(), "filtered": len(filtered)}


def scan(connection, as_of: str, *, setups=None, setup_params=None, risk_params=None, scorecard=None,
         events=None, top: int = 10, jev_client=None, jev_cache=None) -> dict:
    universe = prepare_universe(connection, as_of, events=events)
    restrictions = restrictions_on(connection, as_of, through=_shift(as_of, 4))
    result = evaluate_day(universe, as_of, setups=setups, setup_params=setup_params,
                          risk_params=risk_params, scorecard=scorecard, restrictions=restrictions)
    jev = None
    if jev_client is not None:
        # Judge a few more than ``top`` so filtered names can be replaced.
        jev = apply_jev(universe, as_of, result, jev_client, cache=jev_cache, scorecard=scorecard, limit=top * 3)
    for candidate in result["candidates"][:top]:
        if candidate["fo"] is not None:
            chain = option_chain(connection, candidate["symbol"], as_of)
            if chain:
                candidate["fo"].update(_rounded(option_context(chain, as_of)))
    traded = [f for f in universe.features.values() if f.index_of(as_of) is not None]
    notes = list(universe.notes)
    if not traded:
        notes.append(f"No bars on {as_of}; is it a trading day with imported data?")
    if scorecard is None:
        notes.append("No scorecard supplied: setup edge is unmeasured (run `backtest` first)")
    elif max(scorecard.get("period", {}).get("to", ""), scorecard.get("period", {}).get("data_through", "")) >= as_of:
        notes.append("Scorecard period overlaps the scan date; its track record is in-sample")
    if jev is not None:
        if jev["proof"]["status"] == "PROVEN":
            notes.append(f"Jev is PROVEN ({jev['proof']['reason']}): it filtered {jev['filtered']} candidate(s) "
                         "and contributes 20% of the score")
        else:
            notes.append(f"Jev shown for information only ({jev['proof']['status']}): {jev['proof']['reason']}")
    return {
        "as_of": as_of,
        "universe": {"symbols_with_data": len(universe.features), "traded_on_date": len(traded)},
        "regime": result["regime"],
        "setups": list(setups or SETUPS),
        "risk_params": {k: v for k, v in {**DEFAULT_RISK_PARAMS, **(risk_params or {})}.items()
                        if not isinstance(v, tuple)},
        "candidates": result["candidates"][:top],
        "candidates_total": len(result["candidates"]),
        "rejected": result["rejected"],
        "jev": jev,
        "notes": notes,
        "advisory": "Research output, not investment advice. Setups can fail; gaps can exceed planned stops.",
    }


def _money(value) -> str:
    if value is None:
        return "-"
    if value >= 1e7:
        return f"₹{value / 1e7:.2f} cr"
    if value >= 1e5:
        return f"₹{value / 1e5:.2f} lakh"
    return f"₹{value:,.0f}"


def _short(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}" if abs(value) >= 1 else f"{value:.3f}"
    if isinstance(value, list):
        return "/".join(_short(item) for item in value)
    return str(value)


def _jev_cell(jev: dict | None) -> str:
    if not jev:
        return "-"
    if jev["status"] != "JUDGED":
        return "unavailable"
    crowded = ", crowded" if jev["crowding_risk"] >= 0.6 else ""
    return f"{jev['follow_through']:.0%} to T1, catalyst {jev['catalyst_quality']}{crowded} ({jev['proof']})"


def to_markdown(report: dict) -> str:
    regime = report["regime"]
    lines = [
        f"# Trade ideas as of {report['as_of']} (end of day)",
        "",
        f"- Regime: **{regime['label']}**. {'; '.join(regime['reasons'])}",
        f"- Universe: {report['universe']['traded_on_date']} symbols traded; "
        f"{report['candidates_total']} qualified with full risk plans.",
    ]
    capital = report["risk_params"].get("capital")
    if capital:
        lines.append(f"- Capital {_money(capital)}, risk per trade {report['risk_params']['risk_per_trade']:.2%}.")
    for note in report["notes"]:
        lines.append(f"- Note: {note}")
    lines += [
        "",
        "| # | Symbol | Setup | Catalyst | Key signals | Entry above | Stop | T1 | T2 | R:R net | Time stop | Qty (value) | Track record | Jev |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in report["candidates"]:
        plan, track = c["plan"], c["track_record"]
        catalyst = "-" if not c["catalyst"] else (
            f"{c['catalyst']['type']} {c['catalyst']['date']}" + ("" if c["catalyst"]["verified"] else " (verify)")
        )
        signals = ", ".join(f"{k}={_short(v)}" for k, v in list(c["evidence"].items())[:3])
        if c["fo"]:
            signals += f"; F&O {c['fo']['quadrant']}"
        qty = "-" if plan["shares"] is None else f"{plan['shares']} ({_money(plan['position_value'])})"
        record = track["status"] if track["status"] != "PROVEN" else (
            f"{track['trades']} trades, {track['hit_rate']:.0%} hit, {track['expectancy_r']:+.2f}R"
        )
        lines.append(
            f"| {c['rank']} | {c['symbol']} | {c['setup']} | {catalyst} | {signals} | {plan['entry']:.2f} | "
            f"{plan['stop']:.2f} | {plan['t1']:.2f} | {plan['t2']:.2f} | {plan['reward_risk_after_costs']:.2f} | "
            f"{plan['time_stop_sessions']} sessions | {qty} | {record} | {_jev_cell(c.get('jev'))} |"
        )
    if not report["candidates"]:
        lines.append("| - | No candidate passed the setups and hard risk rules | | | | | | | | | | | | |")
    if report["rejected"]:
        lines += ["", "## Blocked or rejected", ""]
        for item in report["rejected"][:25]:
            lines.append(f"- {item['symbol']} ({', '.join(item['setups'])}): {item['code']}, {item['message']}")
    lines += ["", f"_{report['advisory']}_", ""]
    return "\n".join(lines)
