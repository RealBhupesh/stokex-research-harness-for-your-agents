"""Statistical tests that decide whether a setup's backtest edge is real.

A positive average over 30 trades is easy to get by luck, especially when
many setups and regimes are tested at once and signals cluster on the same
days. A setup is PROVEN only when:

1. it has at least ``MIN_TRADES`` trades and positive expectancy;
2. the one-sided lower confidence bound of expectancy is above zero, from a
   bootstrap that resamples contiguous blocks of whole signal days (trades signalled together move
   together), at a confidence corrected for the number of hypotheses tested
   (Bonferroni);
3. expectancy is positive in at least ``MIN_POSITIVE_FOLD_SHARE`` of
   consecutive time folds, so one lucky stretch cannot carry the result.
"""

import hashlib
import random


MIN_TRADES = 30
MIN_SIGNAL_DAYS = 20
MIN_FOLD_SIGNAL_DAYS = 5
BLOCK_SESSIONS = 5
BASE_ALPHA = 0.05
BOOTSTRAP_SAMPLES = 2000
FOLDS = 4
MIN_FOLD_TRADES = 5
MIN_POSITIVE_FOLD_SHARE = 0.6


def _seed(label: str) -> int:
    return int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:12], 16)


def cluster_bootstrap_lower_bound(trades: list[dict], alpha: float, *, samples: int = BOOTSTRAP_SAMPLES,
                                  label: str = "") -> float | None:
    """One-sided lower bound of mean R using circular blocks of complete signal-date clusters."""
    clusters: dict = {}
    for trade in trades:
        clusters.setdefault(trade["signal_date"], []).append(trade["r_multiple"])
    groups = [clusters[day] for day in sorted(clusters)]
    if len(groups) < 2:
        return None
    rng = random.Random(_seed(label))
    means = []
    for _ in range(samples):
        total = count = 0
        drawn = []
        while len(drawn) < len(groups):
            start = rng.randrange(len(groups))
            drawn.extend(groups[(start + offset) % len(groups)]
                         for offset in range(min(BLOCK_SESSIONS, len(groups))))
        for group in drawn[:len(groups)]:
            total += sum(group)
            count += len(group)
        means.append(total / count)
    means.sort()
    index = max(0, min(len(means) - 1, int(alpha * len(means))))
    return means[index]


def fold_stability(trades: list[dict], folds: int = FOLDS) -> dict:
    """Expectancy in disjoint consecutive folds of complete signal-date clusters."""
    clusters = {}
    for trade in trades:
        clusters.setdefault(trade["signal_date"], []).append(trade)
    days = sorted(clusters)
    rows = []
    for index in range(folds):
        subset = days[index * len(days) // folds:(index + 1) * len(days) // folds]
        if not subset:
            continue
        chunk = [trade for day in subset for trade in clusters[day]]
        rows.append({
            "from": subset[0], "to": subset[-1], "trades": len(chunk), "signal_days": len(subset),
            "expectancy_r": round(sum(t["r_multiple"] for t in chunk) / len(chunk), 4),
        })
    usable = [row for row in rows if row["trades"] >= MIN_FOLD_TRADES
              and row["signal_days"] >= MIN_FOLD_SIGNAL_DAYS]
    share = sum(row["expectancy_r"] > 0 for row in usable) / len(usable) if usable else None
    return {"folds": rows, "usable_folds": len(usable),
            "positive_share": None if share is None else round(share, 4)}


def assess(trades: list[dict], hypotheses: int, label: str) -> dict:
    """Status plus the evidence behind it for one group of trades."""
    trades = [t for t in trades if t.get("exit_reason") != "END_OF_DATA"]
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
    signal_days = len({t["signal_date"] for t in trades})
    if signal_days < MIN_SIGNAL_DAYS:
        reasons.append(f"Only {signal_days} distinct signal days (need {MIN_SIGNAL_DAYS})")
    if stability["usable_folds"] < FOLDS:
        reasons.append(f"Only {stability['usable_folds']} usable time folds (need {FOLDS})")
    share = stability["positive_share"]
    if share is None or share < MIN_POSITIVE_FOLD_SHARE:
        reasons.append(f"Positive in fewer than {MIN_POSITIVE_FOLD_SHARE:.0%} of time folds")
    return {
        "status": "UNPROVEN" if reasons else "PROVEN",
        "reasons": reasons,
        "expectancy_lower_bound": None if lower is None else round(lower, 4),
        "confidence": round(1 - alpha, 5),
        "hypotheses_tested": hypotheses,
        "signal_days": signal_days,
        "bootstrap_block_sessions": BLOCK_SESSIONS,
        "fold_stability": stability,
    }
