"""Forward-test journal with explicit recording provenance.

``scan --journal`` records each pick with its frozen plan and judge opinions.
``journal-update`` later replays the following sessions through the same fill
and exit rules as the backtester and stores the outcome. ``journal-report``
summarises live results per setup and how well Jev or the model predicted them.
"""

from datetime import datetime, timezone, timedelta
import json

from ..jev.calibration import evaluate_jev
from ..market.queries import load_history
from .engine import _stats, simulate_trade


def record_scan(connection, report: dict) -> int:
    """Store a scan's ranked candidates; re-recording the same day keeps the first entry."""
    now = datetime.now(timezone.utc)
    recorded_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    local = now.astimezone(timezone(timedelta(hours=5, minutes=30)))
    future_data = any(connection.execute(f"SELECT 1 FROM {table} WHERE trade_date > ? LIMIT 1",
                                        (report["as_of"],)).fetchone()
                      for table in ("bars", "index_bars", "fo_bars"))
    session_present = all(connection.execute(
        "SELECT 1 FROM bars WHERE symbol = ? AND trade_date = ? AND available_at <= ? LIMIT 1",
        (candidate["symbol"], report["as_of"], recorded_at)).fetchone()
        for candidate in report["candidates"])
    forward = (session_present and local.date().isoformat() == report["as_of"]
               and (local.hour, local.minute) >= (15, 30) and not future_data)
    origin = {"version": 1, "origin": "FORWARD" if forward else "RETROSPECTIVE",
              "recorded_at": recorded_at, "future_market_data_present": future_data,
              "signal_session_present": session_present}
    written = 0
    for candidate in report["candidates"]:
        judges = {key: candidate.get(key) for key in ("jev", "model") if candidate.get(key)}
        judges["_record"] = origin
        cursor = connection.execute(
            "INSERT OR IGNORE INTO journal (scan_date, symbol, setup, setup_version, rank, plan_json, judge_json, "
            "regime, recorded_at, outcome_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (report["as_of"], candidate["symbol"], candidate["setup"], candidate["setup_version"],
             candidate["rank"], json.dumps(candidate["plan"], sort_keys=True), json.dumps(judges, sort_keys=True),
             report["regime"]["label"], recorded_at),
        )
        written += cursor.rowcount
    connection.commit()
    return written


def _adjustment_factor(series, reference_date: str) -> float:
    factor = 1.0
    for event in getattr(series, "adjustments", []):
        if event["ex_date"] > reference_date:
            factor *= event["factor"]
    return factor


def _rescaled_plan(plan: dict, series, scan_date: str) -> dict:
    """Bring frozen plan prices onto the simulator's adjusted replay scale."""
    factor = _adjustment_factor(series, scan_date)
    if factor == 1.0:
        return plan
    scaled = dict(plan)
    for key in ("entry", "stop", "t1", "t2", "round_trip_cost_per_share"):
        if scaled.get(key) is not None:
            scaled[key] = scaled[key] * factor
    return scaled


def _normalise_outcome_prices(outcome: dict, series, scan_date: str, as_of: str) -> dict:
    """Expose prices comparable with the frozen plan, preserving replay inputs.

    Session-native prices undo only adjustments after each simulated execution
    date. No share conversion is inferred from an adjustment factor: vendor
    discontinuity adjustments need not establish a legally changed share count.
    """
    factor = _adjustment_factor(series, scan_date)
    fields = ("fill", "initial_stop", "round_trip_cost_per_share")
    replay = {key: outcome[key] for key in fields if key in outcome}
    replay["legs"] = [dict(leg) for leg in outcome["legs"]]
    replay.update(price_units="AS_OF_ADJUSTED", as_of=as_of)
    result = dict(outcome)
    for key in fields:
        if key in result:
            result[key] = round(result[key] / factor, 4)
    result["legs"] = [{**leg, "price": round(leg["price"] / factor, 4)}
                      for leg in outcome["legs"]]
    native = {"price_units": "EXECUTION_SESSION_NATIVE",
              "fill": round(outcome["fill"] / _adjustment_factor(series, outcome["entry_date"]), 4),
              "legs": [{**leg, "price": round(leg["price"] / _adjustment_factor(series, leg["date"]), 4)}
                       for leg in outcome["legs"]]}
    return {**result, "price_units": "SIGNAL_SESSION", "price_reference_date": scan_date,
            "replay_adjustment_factor": factor, "replay_prices": replay,
            "simulated_session_prices": native, "share_units": "NOT_RECONSTRUCTED"}


def update_outcomes(connection, as_of: str) -> dict:
    """Evaluate journal entries that are not yet closed using data up to ``as_of``."""
    rows = connection.execute(
        "SELECT scan_date, symbol, setup, plan_json, outcome_json FROM journal WHERE scan_date < ? "
        "ORDER BY scan_date, symbol", (as_of,),
    ).fetchall()
    counts = {"closed": 0, "open": 0, "not_filled": 0, "missing_data": 0, "already_final": 0}
    for scan_date, symbol, setup, plan_json, outcome_json in rows:
        if outcome_json and json.loads(outcome_json)["status"] in {"CLOSED", "NOT_FILLED"}:
            previous = json.loads(outcome_json)
            if previous["status"] == "CLOSED" and "price_units" not in previous and previous.get("as_of"):
                original_series = load_history(connection, symbol, previous["as_of"])
                normalised = _normalise_outcome_prices(previous, original_series, scan_date, previous["as_of"])
                connection.execute(
                    "UPDATE journal SET outcome_json = ? WHERE scan_date = ? AND symbol = ? AND setup = ?",
                    (json.dumps(normalised, sort_keys=True), scan_date, symbol, setup))
            counts["already_final"] += 1
            continue
        series = load_history(connection, symbol, as_of)
        if scan_date not in series.dates:
            counts["missing_data"] += 1
            continue
        index = series.dates.index(scan_date)
        plan = _rescaled_plan(json.loads(plan_json), series, scan_date)
        trade = simulate_trade(series, index, plan, cost_bps=0)
        if trade is None:
            outcome = {"status": "OPEN", "as_of": as_of, "reason": "No session after the scan yet"}
            counts["open"] += 1
        elif not trade["filled"]:
            outcome = {"status": "NOT_FILLED", "as_of": as_of, "reason": trade.get("reason", "Trigger not reached")}
            counts["not_filled"] += 1
        elif trade["exit_reason"] == "END_OF_DATA":
            outcome = {"status": "OPEN", "as_of": as_of, "mark_r": round(trade["r_multiple"], 4),
                       "entry_date": trade["entry_date"]}
            counts["open"] += 1
        else:
            outcome = {"status": "CLOSED", "as_of": as_of, **{
                key: trade[key] for key in ("entry_date", "exit_date", "fill", "exit_reason", "legs",
                                            "return_pct", "r_multiple", "sessions_held")},
                "t1_hit": any(leg["reason"] in {"T1", "T2"} for leg in trade["legs"]),
                "initial_stop": trade["initial_stop"],
                "round_trip_cost_per_share": trade["round_trip_cost_per_share"]}
            outcome = _normalise_outcome_prices(outcome, series, scan_date, as_of)
            counts["closed"] += 1
        connection.execute(
            "UPDATE journal SET outcome_json = ? WHERE scan_date = ? AND symbol = ? AND setup = ?",
            (json.dumps(outcome, sort_keys=True), scan_date, symbol, setup),
        )
    connection.commit()
    return counts


def _origin(judges: dict, scan_date: str, recorded_at: str) -> str:
    metadata = judges.get("_record") or {}
    if metadata.get("version") != 1:
        return "UNKNOWN"
    if metadata.get("origin") != "FORWARD":
        return "RETROSPECTIVE"
    try:
        stamp = datetime.strptime(recorded_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        local = stamp.astimezone(timezone(timedelta(hours=5, minutes=30)))
        valid = (metadata.get("recorded_at") == recorded_at
                 and local.date().isoformat() == scan_date
                 and (local.hour, local.minute) >= (15, 30)
                 and metadata.get("future_market_data_present") is False
                 and metadata.get("signal_session_present") is True)
        return "FORWARD" if valid else "UNKNOWN"
    except (ValueError, TypeError):
        return "UNKNOWN"


def closed_trades(connection, *, forward_only: bool = True) -> list[dict]:
    trades = []
    for scan_date, symbol, setup, judge_json, regime, outcome_json, recorded_at in connection.execute(
        "SELECT scan_date, symbol, setup, judge_json, regime, outcome_json, recorded_at FROM journal "
        "WHERE outcome_json IS NOT NULL ORDER BY scan_date, symbol"
    ):
        outcome = json.loads(outcome_json)
        if outcome["status"] != "CLOSED":
            continue
        judges = json.loads(judge_json or "{}")
        origin = _origin(judges, scan_date, recorded_at)
        if forward_only and origin != "FORWARD":
            continue
        trades.append({
            "record_origin": origin,
            "signal_date": scan_date, "symbol": symbol, "setup": setup, "regime": regime, **outcome,
            "jev_p": (judges.get("jev") or {}).get("follow_through"),
            "model_p": (judges.get("model") or {}).get("follow_through"),
        })
    return trades


def live_records(connection) -> dict:
    """Live (journal) statistics per setup, for display next to the backtest record."""
    by_setup: dict = {}
    for trade in closed_trades(connection):
        by_setup.setdefault(trade["setup"], []).append(trade)
    return {setup: _stats(trades) for setup, trades in by_setup.items()}


def report(connection) -> dict:
    trades = closed_trades(connection)
    statuses: dict = {}
    origins: dict = {}
    for outcome_json, judge_json, scan_date, recorded_at in connection.execute(
            "SELECT outcome_json, judge_json, scan_date, recorded_at FROM journal"):
        origin = _origin(json.loads(judge_json or "{}"), scan_date, recorded_at)
        origins[origin] = origins.get(origin, 0) + 1
        status = json.loads(outcome_json)["status"] if outcome_json else "PENDING"
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "entries": statuses,
        "record_origins": origins,
        "excluded_from_live": sum(n for origin, n in origins.items() if origin != "FORWARD"),
        "overall": _stats(trades),
        "by_setup": live_records(connection),
        "jev_live_calibration": evaluate_jev(trades, key="jev_p") if any(t["jev_p"] is not None for t in trades)
        else None,
        "model_live_calibration": evaluate_jev(trades, key="model_p")
        if any(t["model_p"] is not None for t in trades) else None,
        "note": "Live statistics include only scans recorded after session close on the signal date, "
                "before future market data was loaded. Retrospective and legacy entries are excluded. "
                "Journal outcomes remain simulated fills, not broker execution evidence.",
    }
