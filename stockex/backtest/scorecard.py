"""Frozen setup scorecards: the measured edge that ``scan`` uses for ranking."""

from datetime import datetime, timezone
import hashlib
import json

from ..signals.setups import SETUP_VERSIONS
from .statistics import MIN_TRADES, assess


# Version 3: distinct-session folds, block bootstrap, and completed outcomes only.
SCORECARD_SCHEMA_VERSION = 3


def data_fingerprint(connection, start: str, end: str) -> str:
    """Hash every market input, including publication times and outcome sessions.

    A conservative whole-input snapshot also captures history before ``start``
    and outcome bars after the last signal. Imports/audit records and journal
    writes do not change this fingerprint because they are not market inputs.
    """
    digest = hashlib.sha256()
    digest.update(json.dumps({"fingerprint_version": 2, "start": start, "end": end},
                             sort_keys=True).encode())
    for table in ("bars", "index_bars", "fo_bars", "deals", "corporate_actions",
                  "index_members", "announcements", "restrictions"):
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
        digest.update(json.dumps([table, columns], separators=(",", ":")).encode())
        # Tables and column names above are fixed schema identifiers, never user input.
        order = ", ".join(f'"{column}"' for column in columns)
        for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            digest.update(json.dumps(list(row), separators=(",", ":"), allow_nan=False).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def build_scorecard(result: dict, fingerprint: str, *, created_at: datetime | None = None) -> dict:
    created = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    trades_by_setup: dict = {}
    for trade in result.get("trades", []):
        if trade.get("exit_reason") == "END_OF_DATA":
            continue
        trades_by_setup.setdefault(trade["setup"], []).append(trade)
    setup_tests = max(1, len(trades_by_setup))
    regime_tests = max(1, len({(t["setup"], t["regime"]) for t in result.get("trades", [])}))
    setups = {}
    for name, version in SETUP_VERSIONS.items():
        report = result["setups"].get(name, {"overall": {"trades": 0}, "by_regime": {}})
        trades = trades_by_setup.get(name, [])
        overall = assess(trades, setup_tests, f"{name}:overall")
        by_regime = {}
        for regime, stats in report["by_regime"].items():
            subset = [t for t in trades if t["regime"] == regime]
            by_regime[regime] = {**stats, **assess(subset, regime_tests, f"{name}:{regime}")}
        setups[name] = {
            "version": version,
            "status": overall["status"],
            "overall": {**report["overall"], **overall},
            "by_regime": by_regime,
        }
    return {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": result["period"],
        "data_sha256": fingerprint,
        "min_trades_for_proven": MIN_TRADES,
        "risk_params": result["risk_params"],
        "setup_params": result["setup_params"],
        "setups": setups,
        "t1_base_rates": result.get("t1_base_rates", {}),
        "jev": None if not result.get("jev") else {
            key: value for key, value in result["jev"].items() if key != "usage"
        },
        "model": result.get("model"),
        "portfolio": {k: v for k, v in result["portfolio"].items() if k != "equity_curve"},
        "rules": [
            "A setup is PROVEN only with at least the minimum trades, positive expectancy after costs, a "
            "multiple-testing-corrected clustered bootstrap lower bound above zero, and positive expectancy in "
            "most time folds.",
            "Use a scorecard only for scans dated after its period (out-of-sample).",
            "Changing a setup's rule bumps its version and invalidates its record here.",
            "Jev influences scans only when its section here is PROVEN for the same question bank and model.",
            "The walk-forward model influences scans only when its out-of-sample predictions here are PROVEN; "
            "when both are PROVEN the one with higher Brier skill is used.",
        ],
    }


def load_scorecard(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        scorecard = json.load(handle)
    if not isinstance(scorecard, dict) or scorecard.get("schema_version") != SCORECARD_SCHEMA_VERSION:
        raise ValueError(f"{path} is not a STOCKEX scorecard (schema_version {SCORECARD_SCHEMA_VERSION})")
    return scorecard
