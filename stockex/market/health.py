"""Explicit, cutoff-aware data gates for unattended research jobs."""

from datetime import date

from .queries import cutoff


def market_health(connection, as_of: str, *, min_symbols: int = 1, min_history: int = 60) -> dict:
    """Check the requested session, never treating an empty scan as healthy."""
    as_of = date.fromisoformat(as_of).isoformat()
    if min_symbols < 1 or min_history < 1:
        raise ValueError("min_symbols and min_history must be positive")
    issues = []

    def issue(code, severity, message, **details):
        issues.append({"code": code, "severity": severity, "message": message, **details})

    integrity = [row[0] for row in connection.execute("PRAGMA quick_check")]
    if integrity != ["ok"]:
        issue("DATABASE_INTEGRITY", "BLOCK", "SQLite integrity check failed", checks=integrity)
    params = (as_of, cutoff(as_of))
    latest = connection.execute(
        "SELECT MAX(trade_date) FROM bars WHERE trade_date <= ? AND available_at <= ?", params
    ).fetchone()[0]
    symbols = connection.execute(
        "SELECT COUNT(DISTINCT symbol) FROM bars WHERE trade_date = ? AND available_at <= ?", params
    ).fetchone()[0]
    if latest != as_of:
        issue("SESSION_MISSING", "BLOCK", "No cutoff-eligible bars for the requested session", latest=latest)
    if symbols < min_symbols:
        issue("UNIVERSE_TOO_SMALL", "BLOCK", "Session coverage is below the configured minimum",
              actual=symbols, required=min_symbols)
    eligible = connection.execute(
        "SELECT COUNT(*) FROM (SELECT symbol FROM bars WHERE trade_date <= ? AND available_at <= ? "
        "GROUP BY symbol HAVING COUNT(DISTINCT trade_date) >= ?) h "
        "WHERE symbol IN (SELECT symbol FROM bars WHERE trade_date = ? AND available_at <= ?)",
        (*params, min_history, *params),
    ).fetchone()[0]
    if eligible < min_symbols:
        issue("HISTORY_TOO_SHORT", "BLOCK", "Too few current symbols have the required history",
              actual=eligible, required_symbols=min_symbols, required_sessions=min_history)
    invalid = connection.execute(
        "SELECT COUNT(*) FROM bars WHERE trade_date <= ? AND available_at <= ? AND "
        "(open <= 0 OR close <= 0 OR low <= 0 OR high < MAX(open, close, low) "
        "OR low > MIN(open, close, high) OR volume < 0 OR ABS(high) > 1e308 "
        "OR delivery_pct < 0 OR delivery_pct > 100 OR delivery_qty < 0 OR delivery_qty > volume "
        "OR traded_value < 0 OR substr(available_at, 1, 10) < trade_date)", params,
    ).fetchone()[0]
    if invalid:
        issue("INVALID_BARS", "BLOCK", "Invalid price, volume, delivery or availability values", rows=invalid)
    benchmark = connection.execute(
        "SELECT COUNT(*) FROM index_bars WHERE index_name = 'NIFTY 50' "
        "AND trade_date = ? AND available_at <= ?", params,
    ).fetchone()[0]
    if not benchmark:
        issue("BENCHMARK_MISSING", "BLOCK", "NIFTY 50 is missing at the session cutoff")
    missing_delivery = connection.execute(
        "SELECT COUNT(*) FROM bars WHERE trade_date = ? AND available_at <= ? AND delivery_pct IS NULL",
        params,
    ).fetchone()[0]
    if missing_delivery:
        issue("DELIVERY_MISSING", "WARN", "Some current bars have no delivery data", rows=missing_delivery)
    for table, code, message in (
        ("restrictions", "RESTRICTIONS_UNVERIFIED", "No surveillance/restriction records supplied"),
        ("corporate_actions", "ACTIONS_UNVERIFIED", "No explicit corporate-action records supplied"),
    ):
        if connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE available_at <= ?", (cutoff(as_of),)
        ).fetchone()[0] == 0:
            issue(code, "WARN", message)
    blocked = any(item["severity"] == "BLOCK" for item in issues)
    return {"as_of": as_of, "status": "BLOCKED" if blocked else "PASS",
            "latest_eligible_session": latest, "symbols": symbols, "symbols_with_history": eligible,
            "requirements": {"min_symbols": min_symbols, "min_history": min_history}, "issues": issues,
            "limitations": "Checks validate supplied data, not source authenticity, universe completeness, "
                           "exchange holidays or the completeness of surveillance and corporate actions."}
