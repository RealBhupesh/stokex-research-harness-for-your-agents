"""Jev as a meta-labeler: judge whether a scanner candidate is worth taking.

The primary setup decides what to trade; Jev estimates whether this instance
reaches its first target before its stop. The state sent to Jev is
anonymized: no symbol, dates, client names or absolute prices, only ratios
and labels, so Jev cannot recall what a known stock did on a known date.
"""

import hashlib

from ..store.records import canonical_json
from .client import JevError


CANDIDATE_QUESTION_BANK_VERSION = "1"

CANDIDATE_QUESTIONS = {
    "follow_through": {
        "type": "noul",
        "instructions": (
            "This is a long trade setup in an Indian listed stock. Entry, stop and first target are given "
            "as percentages from the last close. Will price reach the first target before the stop, "
            "within the time stop?"
        ),
    },
    "catalyst_quality": {
        "type": "score",
        "instructions": "How strong is the catalyst behind this move?",
        "criteria": {
            "none": "No identifiable catalyst; price action only",
            "weak": "Unverified or minor news",
            "moderate": "Verified event likely to change expectations somewhat",
            "strong": "Verified event that clearly changes earnings, risk or share demand",
        },
    },
    "crowding_risk": {
        "type": "noul",
        "instructions": "Is the move already extended or crowded enough that a near-term reversal is likely?",
    },
    "failure_mode": {
        "type": "choice",
        "instructions": "If this trade fails, what is the most likely reason?",
        "criteria": {
            "gap_reversal": "The move reverses or the gap fills",
            "weak_volume": "Follow-through volume does not arrive",
            "market_drag": "The broad market or sector pulls it down",
            "overhead_supply": "Sellers at nearby resistance absorb demand",
            "none_obvious": "No dominant failure mode",
        },
    },
}

# Evidence keys holding absolute prices; they are sent as a percentage from close.
_PRICE_KEYS = {
    "close", "prior_52w_high", "base_high", "sma20", "sma50", "sma200", "pullback_low",
    "deal_price", "gap_floor",
}
# Evidence keys that could identify the stock or date; never sent.
_DROP_KEYS = {"gap_date", "deal_date", "client", "deal_value"}
_ROW_KEYS = (
    "ret1", "ret5", "ret20", "ret60", "rs20", "rs60", "vol_ratio", "deliv_ratio", "atr_pct",
    "close_position", "gap_pct", "base_range20", "atr_contraction",
)


def _pct(value, close):
    return None if value is None or not close else round(value / close - 1, 4)


def _round(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [_round(item) for item in value]
    return value


def _liquidity_bucket(value) -> str:
    crore = (value or 0) / 1e7
    if crore < 10:
        return "under_10_crore"
    if crore < 50:
        return "10_to_50_crore"
    if crore < 200:
        return "50_to_200_crore"
    return "over_200_crore"


def candidate_state(candidate: dict, row: dict, regime: dict) -> dict:
    """Anonymized description of one candidate at its signal close."""
    close = candidate["close"]
    plan = candidate["plan"]
    evidence = {}
    for key, value in candidate["evidence"].items():
        if key in _DROP_KEYS or isinstance(value, str):
            continue
        evidence[key] = _pct(value, close) if key in _PRICE_KEYS else _round(value)
    catalyst = candidate.get("catalyst")
    inputs = regime.get("inputs", {})
    return {
        "setup": candidate["setup"],
        "other_setups": candidate.get("other_setups", []),
        "plan": {
            "entry_pct": _pct(plan["entry"], close),
            "stop_pct": _pct(plan["stop"], close),
            "t1_pct": _pct(plan["t1"], close),
            "t2_pct": _pct(plan["t2"], close),
            "reward_risk_after_costs": plan["reward_risk_after_costs"],
            "time_stop_sessions": plan["time_stop_sessions"],
        },
        "evidence": evidence,
        "technicals": {
            **{key: _round(row.get(key)) for key in _ROW_KEYS},
            "vs_sma20": _pct(close, row.get("sma20")) if row.get("sma20") else None,
            "vs_sma50": _pct(close, row.get("sma50")) if row.get("sma50") else None,
            "vs_sma200": _pct(close, row.get("sma200")) if row.get("sma200") else None,
            "vs_52w_high": _pct(close, row.get("high252")) if row.get("high252") else None,
        },
        "fo": None if not candidate.get("fo") else {
            key: _round(candidate["fo"].get(key)) for key in ("quadrant", "oi_chg1", "oi_chg5", "rollover")
        },
        "catalyst": None if not catalyst else {"type": catalyst.get("type"), "verified": bool(catalyst.get("verified"))},
        "liquidity": _liquidity_bucket(candidate["liquidity"]["median_traded_value_20d"]),
        "market": {
            "regime": regime.get("label"),
            "nifty_ret20": _round(inputs.get("nifty_ret20")),
            "breadth_above_sma50": _round(inputs.get("breadth_above_sma50")),
            "vix": _round(inputs.get("vix")),
            "vix_chg5": _round(inputs.get("vix_chg5")),
        },
    }


def _sha256(model: str, state: dict) -> str:
    payload = {"bank": CANDIDATE_QUESTION_BANK_VERSION, "model": model, "state": state}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _summary(answers: dict, model: str, sha: str, cached: bool) -> dict:
    return {
        "status": "JUDGED",
        "follow_through": answers["follow_through"]["noul"],
        "catalyst_quality": answers["catalyst_quality"]["score"],
        "crowding_risk": answers["crowding_risk"]["noul"],
        "failure_mode": answers["failure_mode"]["choice"],
        "model": model,
        "input_sha256": sha,
        "cached": cached,
    }


class JudgeBudget:
    """Counts new Jev calls across a run so a backtest cannot overspend."""

    def __init__(self, max_calls: int | None):
        self.max_calls = max_calls
        self.calls = self.cached = self.skipped = self.errors = 0

    def allows_call(self) -> bool:
        return self.max_calls is None or self.calls < self.max_calls

    def report(self) -> dict:
        return {"calls": self.calls, "cached": self.cached, "skipped_budget": self.skipped,
                "errors": self.errors, "max_calls": self.max_calls}


def judge_state(state: dict, client, cache=None, budget: JudgeBudget | None = None) -> dict:
    """Judge one anonymized state; failures and budget exhaustion become gaps."""
    budget = budget or JudgeBudget(None)
    model = getattr(client, "model", "unknown")
    sha = _sha256(model, state)
    if cache is not None:
        hit = cache.get(sha, CANDIDATE_QUESTION_BANK_VERSION, model)
        if hit is not None:
            budget.cached += 1
            return _summary(hit["answers"], hit["model"], sha, True)
    if not budget.allows_call():
        budget.skipped += 1
        return {"status": "JEV_UNAVAILABLE", "reason": "call budget exhausted", "input_sha256": sha}
    budget.calls += 1
    try:
        result = client.evaluate(state, CANDIDATE_QUESTIONS)
    except JevError as error:
        budget.errors += 1
        return {"status": "JEV_UNAVAILABLE", "reason": f"{error.code}: {error.message}", "input_sha256": sha}
    if cache is not None:
        cache.put(sha, CANDIDATE_QUESTION_BANK_VERSION, model, result["answers"], result["model"])
    return _summary(result["answers"], result["model"], sha, False)
