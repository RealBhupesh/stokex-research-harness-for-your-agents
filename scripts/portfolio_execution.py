"""Portfolio comparison and execution arithmetic without order placement."""

import math


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def candidate_opportunity_cost(candidate_return, alternative_returns):
    candidate = _finite(candidate_return, "candidate_return")
    if not isinstance(alternative_returns, list) or not alternative_returns:
        raise ValueError("At least one named alternative is required")
    alternatives = []
    for index, alternative in enumerate(alternative_returns):
        if not isinstance(alternative, dict) or not isinstance(alternative.get("name"), str) or not alternative["name"].strip():
            raise ValueError(f"alternative {index} requires a name")
        expected = _finite(alternative.get("expected_return"), f"alternative_returns[{index}].expected_return")
        alternatives.append({"name": alternative["name"], "expected_return": expected})
    best = max(alternatives, key=lambda row: row["expected_return"])
    excess = candidate - best["expected_return"]
    return {
        "candidate_expected_return": candidate,
        "best_alternative": best["name"],
        "best_alternative_expected_return": best["expected_return"],
        "candidate_excess_return": excess,
        "candidate_leads": excess > 0,
        "alternatives": alternatives,
        "warning": "Expected returns must share a horizon, scenario basis, costs and evidence standard before comparison.",
    }


def execution_estimate(order_value, average_daily_traded_value, spread_bps,
                       slippage_bps, fees_bps, participation_rate=0.10):
    order = _finite(order_value, "order_value")
    adtv = _finite(average_daily_traded_value, "average_daily_traded_value")
    spread = _finite(spread_bps, "spread_bps")
    slippage = _finite(slippage_bps, "slippage_bps")
    fees = _finite(fees_bps, "fees_bps")
    participation = _finite(participation_rate, "participation_rate")
    if order <= 0 or adtv <= 0 or min(spread, slippage, fees) < 0:
        raise ValueError("Order and traded value must be positive; cost inputs must be nonnegative")
    if not 0 < participation <= 1:
        raise ValueError("participation_rate must be greater than zero and at most one")
    friction = (spread + slippage + fees) / 10_000
    daily_capacity = adtv * participation
    return {
        "one_way_friction_fraction": friction,
        "estimated_one_way_friction": order * friction,
        "daily_capacity": daily_capacity,
        "raw_exit_sessions": order / daily_capacity,
        "minimum_exit_sessions": math.ceil(order / daily_capacity),
        "warning": "Spread, slippage and liquidity can deteriorate during stress, gaps or locked circuits; this is not an execution guarantee.",
    }


def position_risk_budget(portfolio_value, max_loss_fraction, entry_price,
                         invalidation_price):
    portfolio = _finite(portfolio_value, "portfolio_value")
    loss_fraction = _finite(max_loss_fraction, "max_loss_fraction")
    entry = _finite(entry_price, "entry_price")
    invalidation = _finite(invalidation_price, "invalidation_price")
    if portfolio <= 0 or not 0 < loss_fraction <= 1 or not entry > invalidation >= 0:
        raise ValueError("Require positive portfolio, loss fraction in (0,1], and entry above nonnegative invalidation")
    loss_budget = portfolio * loss_fraction
    per_share_loss = entry - invalidation
    shares = math.floor(loss_budget / per_share_loss)
    position_value = shares * entry
    return {
        "loss_budget": loss_budget,
        "per_share_loss": per_share_loss,
        "shares": shares,
        "position_value": position_value,
        "planned_loss": shares * per_share_loss,
        "portfolio_weight": position_value / portfolio,
        "warning": "In a gap, circuit or liquidity failure, realized loss can exceed the planned invalidation loss.",
    }
