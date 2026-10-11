"""Forward-test journal: the only fully out-of-sample record of the scanner.

``scan --journal`` records each pick with its frozen plan and judge opinions.
``journal-update`` later replays the following sessions through the same fill
and exit rules as the backtester and stores the outcome. ``journal-report``
summarises live results per setup and how well Jev or the model predicted them.
"""

from datetime import datetime, timezone
import json

from ..jev.calibration import evaluate_jev
from ..market.queries import load_history
from .engine import _stats, simulate_trade


def record_scan(connection, report: dict) -> int:
    """Store a scan's ranked candidates; re-recording the same day keeps the first entry."""
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    for candidate in report["candidates"]:
        judges = {key: candidate.get(key) for key in ("jev", "model") if candidate.get(key)}
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


def _rescaled_plan(plan: dict, series, scan_date: str) -> dict:
    """Bring plan prices onto the adjusted scale when a split or bonus went ex after the scan."""
    factor = 1.0
    for event in getattr(series, "adjustments", []):
        if event["ex_date"] > scan_date:
            factor *= event["factor"]
    if factor == 1.0:
        return plan
    scaled = dict(plan)
    for key in ("entry", "stop", "t1", "t2", "round_trip_cost_per_share"):
        if scaled.get(key) is not None:
            scaled[key] = scaled[key] * factor
    return scaled


def update_outcomes(connection, as_of: str) -> dict:
    """Evaluate journal entries that are not yet closed using data up to ``as_of``."""
    rows = connection.execute(
        "SELECT scan_date, symbol, setup, plan_json, outcome_json FROM journal WHERE scan_date < ? "
        "ORDER BY scan_date, symbol", (as_of,),
    ).fetchall()
    counts = {"closed": 0, "open": 0, "not_filled": 0, "missing_data": 0, "already_final": 0}
    for scan_date, symbol, setup, plan_json, outcome_json in rows:
        if outcome_json and json.loads(outcome_json)["status"] in {"CLOSED", "NOT_FILLED"}:
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
                "t1_hit": any(leg["reason"] in {"T1", "T2"} for leg in trade["legs"])}
            counts["closed"] += 1
        connection.execute(
            "UPDATE journal SET outcome_json = ? WHERE scan_date = ? AND symbol = ? AND setup = ?",
            (json.dumps(outcome, sort_keys=True), scan_date, symbol, setup),
        )
    connection.commit()
    return counts


def closed_trades(connection) -> list[dict]:
    trades = []
    for scan_date, symbol, setup, judge_json, regime, outcome_json in connection.execute(
        "SELECT scan_date, symbol, setup, judge_json, regime, outcome_json FROM journal "
        "WHERE outcome_json IS NOT NULL ORDER BY scan_date, symbol"
    ):
        outcome = json.loads(outcome_json)
        if outcome["status"] != "CLOSED":
            continue
        judges = json.loads(judge_json or "{}")
        trades.append({
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
    for (outcome_json,) in connection.execute("SELECT outcome_json FROM journal"):
        status = json.loads(outcome_json)["status"] if outcome_json else "PENDING"
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "entries": statuses,
        "overall": _stats(trades),
        "by_setup": live_records(connection),
        "jev_live_calibration": evaluate_jev(trades, key="jev_p") if any(t["jev_p"] is not None for t in trades)
        else None,
        "model_live_calibration": evaluate_jev(trades, key="model_p")
        if any(t["model_p"] is not None for t in trades) else None,
        "note": "Live results are the true out-of-sample test. Compare them with the backtest scorecard before "
                "trusting a setup or judge.",
    }
