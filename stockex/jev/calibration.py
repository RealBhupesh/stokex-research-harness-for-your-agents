"""Prove (or not) that Jev's follow-through probabilities improve on the setups alone.

A judged trade carries ``jev_p`` (Jev's probability of reaching T1 before the
stop), ``t1_hit`` (whether it did) and ``r_multiple``. Jev is PROVEN only when
its probabilities beat each setup's base rate on both calibration (Brier skill)
and ranking (AUC), and filtering on them raises expectancy.
"""

MIN_JUDGED_TRADES = 50
MIN_AUC = 0.55


def brier(probabilities: list[float], outcomes: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)


def auc(probabilities: list[float], outcomes: list[int]) -> float | None:
    """Mann-Whitney AUC: chance a random hit is ranked above a random miss (ties count half)."""
    positives = [p for p, y in zip(probabilities, outcomes) if y]
    negatives = [p for p, y in zip(probabilities, outcomes) if not y]
    if not positives or not negatives:
        return None
    wins = 0.0
    for p in positives:
        for q in negatives:
            wins += 1.0 if p > q else 0.5 if p == q else 0.0
    return wins / (len(positives) * len(negatives))


def reliability(probabilities: list[float], outcomes: list[int], buckets: int = 5) -> list[dict]:
    rows = []
    for index in range(buckets):
        low, high = index / buckets, (index + 1) / buckets
        members = [(p, y) for p, y in zip(probabilities, outcomes)
                   if low <= p < high or (index == buckets - 1 and p == 1.0)]
        rows.append({
            "range": [round(low, 2), round(high, 2)],
            "count": len(members),
            "mean_probability": round(sum(p for p, _ in members) / len(members), 4) if members else None,
            "observed_rate": round(sum(y for _, y in members) / len(members), 4) if members else None,
        })
    return rows


def _expectancy(trades: list[dict]) -> float | None:
    return round(sum(t["r_multiple"] for t in trades) / len(trades), 4) if trades else None


def _rounded_auc(trades: list[dict]) -> float | None:
    value = auc([t["jev_p"] for t in trades], [1 if t["t1_hit"] else 0 for t in trades])
    return None if value is None else round(value, 4)


def evaluate_jev(trades: list[dict]) -> dict:
    """Calibration report over judged trades, with per-setup base rates."""
    judged = [t for t in trades if t.get("jev_p") is not None]
    by_setup: dict = {}
    for trade in judged:
        by_setup.setdefault(trade["setup"], []).append(trade)
    base_rates = {
        setup: round(sum(t["t1_hit"] for t in items) / len(items), 4) for setup, items in sorted(by_setup.items())
    }
    report = {
        "judged_trades": len(judged),
        "unjudged_trades": len(trades) - len(judged),
        "base_rates": base_rates,
    }
    if not judged:
        return {**report, "status": "UNPROVEN", "reasons": ["No judged trades"]}
    ps = [t["jev_p"] for t in judged]
    ys = [1 if t["t1_hit"] else 0 for t in judged]
    base = [base_rates[t["setup"]] for t in judged]
    jev_brier, base_brier = brier(ps, ys), brier(base, ys)
    skill = None if base_brier == 0 else 1 - jev_brier / base_brier
    ranking = auc(ps, ys)
    kept = [t for t in judged if t["jev_p"] >= base_rates[t["setup"]]]
    filtered, unfiltered = _expectancy(kept), _expectancy(judged)
    reasons = []
    if len(judged) < MIN_JUDGED_TRADES:
        reasons.append(f"Only {len(judged)} judged trades (need {MIN_JUDGED_TRADES})")
    if skill is None or skill <= 0:
        reasons.append("Brier skill vs setup base rates is not positive")
    if ranking is None or ranking <= MIN_AUC:
        reasons.append(f"AUC not above {MIN_AUC}")
    if filtered is None or unfiltered is None or filtered <= unfiltered:
        reasons.append("Filtering on Jev does not raise expectancy")
    return {
        **report,
        "status": "UNPROVEN" if reasons else "PROVEN",
        "reasons": reasons,
        "brier": round(jev_brier, 5),
        "base_brier": round(base_brier, 5),
        "brier_skill": None if skill is None else round(skill, 4),
        "auc": None if ranking is None else round(ranking, 4),
        "reliability": reliability(ps, ys),
        "filtered": {"trades": len(kept), "expectancy_r": filtered},
        "unfiltered": {"trades": len(judged), "expectancy_r": unfiltered},
        "by_setup": {
            setup: {
                "judged_trades": len(items),
                "base_rate": base_rates[setup],
                "auc": _rounded_auc(items),
            }
            for setup, items in sorted(by_setup.items())
        },
    }
