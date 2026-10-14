"""Prove (or not) that Jev's follow-through probabilities improve on the setups alone.

A judged trade carries ``jev_p`` (Jev's probability of reaching T1 before the
stop), ``t1_hit`` (whether it did) and ``r_multiple``. Jev is PROVEN only when
its probabilities beat each setup's base rate on both calibration (Brier skill)
and ranking (AUC), and filtering on them raises expectancy.
"""

from datetime import date
import math
import random

MIN_JUDGED_TRADES = 50
MIN_SIGNAL_DAYS = 20
FOLDS = 4
MIN_FOLD_SIGNAL_DAYS = 5
BOOTSTRAP_SAMPLES = 1000
PROOF_VERSION = 2
MIN_AUC = 0.55


def brier(probabilities: list[float], outcomes: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(outcomes)


def auc(probabilities: list[float], outcomes: list[int]) -> float | None:
    """Mann-Whitney AUC: chance a random hit is ranked above a random miss (ties count half)."""
    ordered = sorted(zip(probabilities, outcomes))
    positives = sum(y for _, y in ordered)
    negatives = len(ordered) - positives
    if not positives or not negatives:
        return None
    wins = below = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        hits = sum(y for _, y in ordered[index:end])
        misses = end - index - hits
        wins += hits * (below + misses / 2)
        below += misses
        index = end
    return wins / (positives * negatives)


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


def _rounded_auc(trades: list[dict], key: str = "jev_p") -> float | None:
    value = auc([t[key] for t in trades], [1 if t["t1_hit"] else 0 for t in trades])
    return None if value is None else round(value, 4)


def _dated(t: dict) -> bool:
    try:
        signal, end = t['signal_date'], t['exit_date']
        return (date.fromisoformat(signal).isoformat() == signal
                and date.fromisoformat(end).isoformat() == end and end > signal)
    except (KeyError, TypeError, ValueError):
        return False


def _metrics(items: list[dict], key: str) -> tuple:
    ps, ys = [t[key] for t in items], [int(t['t1_hit']) for t in items]
    gain = sum((t['_base'] - y) ** 2 - (p - y) ** 2
               for t, p, y in zip(items, ps, ys)) / len(items)
    kept = [t for t in items if t[key] >= t['_base']]
    uplift = (sum(t['r_multiple'] for t in kept) / len(kept)
              - sum(t['r_multiple'] for t in items) / len(items)) if kept else None
    return gain, auc(ps, ys), uplift


def evaluate_jev(trades: list[dict], key: str = 'jev_p') -> dict:
    """Proof using prior completed setup baselines and block-clustered uncertainty.

    Whole signal sessions are resampled in five-session blocks. Three claims
    for each of two judges share a 5% error budget. Full-sample base rates are
    descriptive only; filtering uses Laplace-smoothed prior completed outcomes.
    """
    judged, invalid = [], 0
    for t in trades:
        if t.get(key) is None:
            continue
        p, r = t[key], t.get('r_multiple')
        if (not isinstance(p, (int, float)) or isinstance(p, bool) or not math.isfinite(p)
                or not 0 <= p <= 1 or not isinstance(r, (int, float)) or not math.isfinite(r)
                or t.get('t1_hit') not in (True, False) or not t.get('setup')
                or t.get('exit_reason') == 'END_OF_DATA'):
            invalid += 1
            continue
        judged.append(dict(t))
    by_setup = {}
    for t in judged:
        by_setup.setdefault(t['setup'], []).append(t)
    rates = {setup: round(sum(t['t1_hit'] for t in items) / len(items), 4)
             for setup, items in sorted(by_setup.items())}
    missing_dates = sum(not _dated(t) for t in judged)
    completed = sorted((t for t in trades if _dated(t) and t.get('setup')
                        and t.get('t1_hit') in (True, False)
                        and t.get('exit_reason') != 'END_OF_DATA'), key=lambda t: t['exit_date'])
    prior, cursor = {}, 0
    for t in sorted(judged, key=lambda t: str(t.get('signal_date', ''))):
        signal = t.get('signal_date') if _dated(t) else ''
        while cursor < len(completed) and completed[cursor]['exit_date'] < signal:
            old = completed[cursor]
            count, hits = prior.get(old['setup'], (0, 0))
            prior[old['setup']] = count + 1, hits + int(old['t1_hit'])
            cursor += 1
        count, hits = prior.get(t['setup'], (0, 0))
        t['_base'] = (hits + 1) / (count + 2)
    report = {'proof_version': PROOF_VERSION, 'judged_trades': len(judged),
              'unjudged_trades': sum(t.get(key) is None for t in trades), 'invalid_trades': invalid,
              'base_rates': rates, 'baseline_method': 'prior_completed_setup_laplace_1_1'}
    if not judged:
        return {**report, 'status': 'UNPROVEN', 'reasons': ['No valid judged trades']}
    ps, ys = [t[key] for t in judged], [int(t['t1_hit']) for t in judged]
    score, base = brier(ps, ys), brier([t['_base'] for t in judged], ys)
    skill = None if base == 0 else 1 - score / base
    gain, ranking, uplift = _metrics(judged, key)
    kept = [t for t in judged if t[key] >= t['_base']]
    clusters = {}
    for t in judged:
        if _dated(t):
            clusters.setdefault(t['signal_date'], []).append(t)
    days = sorted(clusters)
    groups = [clusters[d] for d in days]
    alpha, bounds = .05 / 6, [None] * 3
    if len(days) >= MIN_SIGNAL_DAYS and len(judged) >= MIN_JUDGED_TRADES and not missing_dates:
        rng, estimates = random.Random(42971), [[], [], []]
        for _ in range(BOOTSTRAP_SAMPLES):
            drawn = []
            while len(drawn) < len(groups):
                start = rng.randrange(len(groups))
                drawn.extend(groups[(start + offset) % len(groups)]
                             for offset in range(min(5, len(groups))))
            values = _metrics([t for group in drawn[:len(groups)] for t in group], key)
            for i, value in enumerate(values):
                estimates[i].append(float('-inf') if value is None else value)
        bounds = [sorted(values)[int(alpha * BOOTSTRAP_SAMPLES)] for values in estimates]
    folds = []
    for i in range(FOLDS):
        subset = days[i * len(days) // FOLDS:(i + 1) * len(days) // FOLDS]
        if not subset:
            continue
        items = [t for d in subset for t in clusters[d]]
        improvement, rank, lift = _metrics(items, key)
        folds.append({'from': subset[0], 'to': subset[-1], 'signal_days': len(subset),
                      'trades': len(items), 'brier_improvement': round(improvement, 5),
                      'auc': rank, 'expectancy_uplift_r': lift,
                      'positive': improvement > 0 and rank is not None and rank > MIN_AUC
                                  and lift is not None and lift > 0})
    usable = [f for f in folds if f['signal_days'] >= MIN_FOLD_SIGNAL_DAYS]
    reasons = []
    if len(judged) < MIN_JUDGED_TRADES:
        reasons.append(f'Only {len(judged)} judged trades (need {MIN_JUDGED_TRADES})')
    if invalid:
        reasons.append(f'{invalid} invalid or censored judged trades')
    if missing_dates:
        reasons.append(f'{missing_dates} judged trades lack valid signal/exit provenance')
    if len(days) < MIN_SIGNAL_DAYS:
        reasons.append(f'Only {len(days)} distinct signal days (need {MIN_SIGNAL_DAYS})')
    if skill is None or skill <= 0:
        reasons.append('Brier skill vs setup base rates is not positive')
    if ranking is None or ranking <= MIN_AUC:
        reasons.append(f'AUC not above {MIN_AUC}')
    if uplift is None or uplift <= 0:
        reasons.append('Filtering on these probabilities does not raise expectancy')
    for label, bound, threshold in zip(('Brier improvement', 'AUC', 'Filter expectancy uplift'),
                                       bounds, (0, MIN_AUC, 0)):
        if bound is None or bound <= threshold:
            reasons.append(f'Clustered confidence lower bound for {label} not above {threshold}')
    if len(usable) < FOLDS or sum(f['positive'] for f in usable) < 3:
        reasons.append('Need four usable time folds with improvement in at least three')
    return {**report, 'status': 'UNPROVEN' if reasons else 'PROVEN', 'reasons': reasons,
            'brier': round(score, 5), 'base_brier': round(base, 5),
            'brier_skill': None if skill is None else round(skill, 4),
            'auc': None if ranking is None else round(ranking, 4),
            'signal_days': len(days), 'folds': folds, 'confidence': 1 - alpha,
            'bootstrap_block_sessions': 5,
            'confidence_lower_bounds': {
                label: round(value, 5) if value is not None and math.isfinite(value) else None
                for label, value in zip(('brier_improvement', 'auc', 'expectancy_uplift_r'), bounds)},
            'reliability': reliability(ps, ys),
            'filtered': {'trades': len(kept), 'expectancy_r': _expectancy(kept)},
            'unfiltered': {'trades': len(judged), 'expectancy_r': _expectancy(judged)},
            'by_setup': {setup: {'judged_trades': len(items), 'base_rate': rates[setup],
                                 'auc': _rounded_auc(items, key)}
                         for setup, items in sorted(by_setup.items())}}
