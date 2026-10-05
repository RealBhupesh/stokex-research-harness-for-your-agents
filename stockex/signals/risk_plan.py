"""Hard risk plan: every candidate gets entry, stop, targets, time stop and size, or is rejected.

Sizing mirrors ``scripts/finance_helpers.size_cash_trade`` (a test checks
parity) so the scanner and the manual worksheets agree.
"""

from dataclasses import dataclass, field
import math


DEFAULT_RISK_PARAMS = {
    "capital": None,
    "risk_per_trade": 0.01,
    "max_position_pct": 0.20,
    "min_atr_stop": 1.0,
    "max_atr_stop": 3.0,
    "t1_r": 1.5,
    "t2_r": 3.0,
    "min_reward_risk": 2.0,
    "round_trip_cost_bps": 45.0,
    "min_traded_value": 5e7,
    "max_participation": 0.02,
    "min_price": 20.0,
    "blocked_lists": ("ASM", "GSM", "FO_BAN", "ESM", "SUSPENDED"),
    # BE = trade-for-trade (often surveillance), BZ = non-compliant issuers.
    "blocked_series": ("BE", "BZ"),
    "risk_off_size_multiplier": 0.5,
}


@dataclass
class TradePlan:
    entry: float
    stop: float
    stop_basis: str
    risk_per_share: float
    t1: float
    t2: float
    reward_risk_after_costs: float
    time_stop_sessions: int
    trail_rule: str
    round_trip_cost_per_share: float
    shares: int | None = None
    position_value: float | None = None
    planned_loss: float | None = None
    size_notes: list = field(default_factory=list)


@dataclass
class Rejection:
    code: str
    message: str


def _blocked(labels: list[str], blocked_lists) -> list[str]:
    return [label for label in labels if label.split(":", 1)[0] in blocked_lists]


def build_plan(signal, bar: dict, *, restrictions: list[str] | None = None, regime: str = "UNKNOWN",
               params: dict | None = None):
    """Return a ``TradePlan`` or a ``Rejection`` for one signal.

    ``bar`` needs ``close``, ``high``, ``low``, ``ret1``, ``atr14`` and
    ``value_med20`` for the signal day.
    """
    p = {**DEFAULT_RISK_PARAMS, **(params or {})}
    blocked = _blocked(restrictions or [], p["blocked_lists"])
    if blocked:
        return Rejection("RESTRICTED", f"On restricted list: {', '.join(blocked)}")
    if bar.get("series") in p["blocked_series"]:
        return Rejection("TRADE_FOR_TRADE", f"Series {bar['series']} is trade-for-trade or non-compliant")
    close, atr14, value_med = bar["close"], bar["atr14"], bar["value_med20"]
    if close < p["min_price"]:
        return Rejection("PRICE_TOO_LOW", f"Close {close:.2f} below minimum {p['min_price']:.2f}")
    if not value_med or value_med < p["min_traded_value"]:
        return Rejection("ILLIQUID", f"Median traded value {value_med or 0:,.0f} below {p['min_traded_value']:,.0f}")
    if bar["high"] == bar["low"] == close and abs(bar["ret1"] or 0) >= 0.019:
        return Rejection("CIRCUIT_LOCKED", "Signal day traded at a single price; likely circuit-locked")
    if not atr14:
        return Rejection("ATR_MISSING", "Not enough history for ATR")

    entry = signal.entry
    stop, basis = signal.stop, "structural"
    distance = entry - stop
    if distance < p["min_atr_stop"] * atr14:
        stop, basis = entry - p["min_atr_stop"] * atr14, f"widened to {p['min_atr_stop']:g}x ATR"
    elif distance > p["max_atr_stop"] * atr14:
        return Rejection("STOP_TOO_WIDE", f"Structural stop is {distance / atr14:.1f}x ATR (max {p['max_atr_stop']:g}x)")
    stop = round(stop, 2)
    if stop <= 0:
        return Rejection("STOP_INVALID", "Stop is not above zero")
    risk = entry - stop
    cost = entry * p["round_trip_cost_bps"] / 10_000
    t1, t2 = round(entry + p["t1_r"] * risk, 2), round(entry + p["t2_r"] * risk, 2)
    reward_risk = (t2 - entry - cost) / (risk + cost)
    if reward_risk < p["min_reward_risk"]:
        return Rejection("REWARD_RISK_TOO_LOW", f"Reward/risk after costs {reward_risk:.2f} < {p['min_reward_risk']:g}")

    plan = TradePlan(
        entry=entry, stop=stop, stop_basis=basis, risk_per_share=round(risk, 4), t1=t1, t2=t2,
        reward_risk_after_costs=round(reward_risk, 3), time_stop_sessions=signal.time_stop,
        trail_rule="After T1, sell half and move the stop to entry; trail the rest under the prior 2-session low.",
        round_trip_cost_per_share=round(cost, 4),
    )
    capital = p["capital"]
    if capital:
        risk_budget = capital * p["risk_per_trade"]
        if regime == "RISK_OFF":
            risk_budget *= p["risk_off_size_multiplier"]
            plan.size_notes.append(f"RISK_OFF regime: risk budget x{p['risk_off_size_multiplier']:g}")
        by_risk = math.floor(risk_budget / (risk + cost))
        by_cash = math.floor(capital * p["max_position_pct"] / entry)
        by_liquidity = math.floor(value_med * p["max_participation"] / entry)
        shares = min(by_risk, by_cash, by_liquidity)
        limiter = next(name for value, name in (
            (by_risk, "risk budget"), (by_cash, "max position %"), (by_liquidity, "liquidity")) if value == shares)
        if shares < 1:
            return Rejection("SIZE_ZERO", f"Position rounds to zero shares (limited by {limiter})")
        plan.shares = shares
        plan.position_value = round(shares * entry, 2)
        plan.planned_loss = round(shares * (risk + cost), 2)
        plan.size_notes.append(f"Size limited by {limiter}")
    return plan
