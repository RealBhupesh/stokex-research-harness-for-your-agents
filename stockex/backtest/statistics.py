"""Statistical tests that decide whether a setup's backtest edge is real.

A positive average over 30 trades is easy to get by luck, especially when
many setups and regimes are tested at once and signals cluster on the same
days. A setup is PROVEN only when:

1. it has at least ``MIN_TRADES`` trades and positive expectancy;
2. the one-sided lower confidence bound of expectancy is above zero, from a
   bootstrap that resamples whole signal days (trades signalled together move
   together), at a confidence corrected for the number of hypotheses tested
   (Bonferroni);
3. expectancy is positive in at least ``MIN_POSITIVE_FOLD_SHARE`` of
   consecutive time folds, so one lucky stretch cannot carry the result.
"""

import hashlib
import random


MIN_TRADES = 30
BASE_ALPHA = 0.05
BOOTSTRAP_SAMPLES = 2000
FOLDS = 4
MIN_FOLD_TRADES = 5
MIN_POSITIVE_FOLD_SHARE = 0.6


def _seed(label: str) -> int:
    return int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:12], 16)


def cluster_bootstrap_lower_bound(trades: list[dict], alpha: float, *, samples: int = BOOTSTRAP_SAMPLES,
                                  label: str = "") -> float | None:
    """One-sided lower bound of mean R, resampling signal dates as clusters."""
    clusters: dict = {}
    for trade in trades:
        clusters.setdefault(trade["signal_date"], []).append(trade["r_multiple"])
    groups = list(clusters.values())
    if len(groups) < 2:
        return None
    rng = random.Random(_seed(label))
    means = []
    for _ in range(samples):
        total = count = 0
        for _ in range(len(groups)):
            group = groups[rng.randrange(len(groups))]
            total += sum(group)
            count += len(group)
        means.append(total / count)
    means.sort()
    index = max(0, min(len(means) - 1, int(alpha * len(means))))
    return means[index]


def fold_stability(trades: list[dict], folds: int = FOLDS) -> dict:
    """Expectancy in consecutive time folds of roughly equal trade counts."""
    ordered = sorted(trades, key=lambda t: (t["signal_date"], t.get("symbol", "")))
    if not ordered:
        return {"folds": [], "positive_share": None}
    size = max(1, len(ordered) // folds)
    chunks = [ordered[i:i + size] for i in range(0, len(ordered), size)]
    if len(chunks) > folds:  # fold the remainder into the last chunk
        chunks[folds - 1].extend(item for chunk in chunks[folds:] for item in chunk)
        chunks = chunks[:folds]
    rows = []
    for chunk in chunks:
        rows.append({
            "from": chunk[0]["signal_date"], "to": chunk[-1]["signal_date"], "trades": len(chunk),
            "expectancy_r": round(sum(t["r_multiple"] for t in chunk) / len(chunk), 4),
        })
    usable = [row for row in rows if row["trades"] >= MIN_FOLD_TRADES]
    share = sum(row["expectancy_r"] > 0 for row in usable) / len(usable) if usable else None
    return {"folds": rows, "positive_share": None if share is None else round(share, 4)}


def assess(trades: list[dict], hypotheses: int, label: str) -> dict:
    """Status plus the evidence behind it for one group of trades."""
    n = len(trades)
    expectancy = sum(t["r_multiple"] for t in trades) / n if n else None
    alpha = BASE_ALPHA / max(1, hypotheses)
    lower = cluster_bootstrap_lower_bound(trades, alpha, label=label) if n >= MIN_TRADES else None
    stability = fold_stability(trades)
    reasons = []
    if n < MIN_TRADES:
        reasons.append(f"Only {n} trades (need {MIN_TRADES})")
    if expectancy is None or expectancy <= 0:
        reasons.append("Expectancy is not positive")
    if n >= MIN_TRADES and (lower is None or lower <= 0):
        reasons.append(f"Lower {1 - alpha:.2%} confidence bound of expectancy is not above zero")
    share = stability["positive_share"]
    if share is None or share < MIN_POSITIVE_FOLD_SHARE:
        reasons.append(f"Positive in fewer than {MIN_POSITIVE_FOLD_SHARE:.0%} of time folds")
    return {
        "status": "UNPROVEN" if reasons else "PROVEN",
        "reasons": reasons,
        "expectancy_lower_bound": None if lower is None else round(lower, 4),
        "confidence": round(1 - alpha, 5),
        "hypotheses_tested": hypotheses,
        "signal_days": len({t["signal_date"] for t in trades}),
        "fold_stability": stability,
    }
