"""Market regime from Nifty trend, breadth and India VIX."""

from .indicators import sma


BENCHMARK_INDEX = "NIFTY 50"
VIX_INDEX = "INDIA VIX"


def benchmark_trend(closes_by_date: dict) -> dict:
    """Per-date Nifty trend inputs: close, 50/200 DMA and 20-day return."""
    dates = sorted(closes_by_date)
    closes = [closes_by_date[day] for day in dates]
    sma50, sma200 = sma(closes, 50), sma(closes, 200)
    result = {}
    for i, day in enumerate(dates):
        result[day] = {
            "close": closes[i],
            "sma50": sma50[i],
            "sma200": sma200[i],
            "ret20": closes[i] / closes[i - 20] - 1 if i >= 20 else None,
        }
    return result


def vix_state(vix_by_date: dict) -> dict:
    dates = sorted(vix_by_date)
    result = {}
    for i, day in enumerate(dates):
        result[day] = {
            "level": vix_by_date[day],
            "chg5": vix_by_date[day] / vix_by_date[dates[i - 5]] - 1 if i >= 5 else None,
        }
    return result


def classify_regime(trend: dict | None, breadth_above50: float | None, vix: dict | None, *,
                    breadth_strong: float = 0.55, breadth_weak: float = 0.35,
                    vix_high: float = 20.0, vix_spike: float = 0.20) -> dict:
    """Return ``RISK_ON``, ``NEUTRAL``, ``RISK_OFF`` or ``UNKNOWN`` with the inputs used."""
    inputs = {
        "nifty_close": trend and trend["close"],
        "nifty_sma50": trend and trend["sma50"],
        "nifty_sma200": trend and trend["sma200"],
        "nifty_ret20": trend and trend["ret20"],
        "breadth_above_sma50": breadth_above50,
        "vix": vix and vix["level"],
        "vix_chg5": vix and vix["chg5"],
    }
    if not trend or trend["sma50"] is None or breadth_above50 is None:
        return {"label": "UNKNOWN", "inputs": inputs, "reasons": ["Insufficient Nifty history or breadth"]}
    positives, negatives = [], []
    if trend["close"] > trend["sma50"]:
        positives.append("Nifty above 50 DMA")
    else:
        negatives.append("Nifty below 50 DMA")
    if trend["sma200"] is not None:
        if trend["sma50"] > trend["sma200"]:
            positives.append("50 DMA above 200 DMA")
        if trend["close"] < trend["sma200"]:
            negatives.append("Nifty below 200 DMA")
    if breadth_above50 >= breadth_strong:
        positives.append(f"Breadth {breadth_above50:.0%} above 50 DMA")
    elif breadth_above50 <= breadth_weak:
        negatives.append(f"Breadth only {breadth_above50:.0%} above 50 DMA")
    if vix:
        if vix["level"] >= vix_high:
            negatives.append(f"India VIX {vix['level']:.1f} is elevated")
        if vix["chg5"] is not None and vix["chg5"] >= vix_spike:
            negatives.append(f"India VIX up {vix['chg5']:.0%} in 5 sessions")
    if len(negatives) >= 2:
        label = "RISK_OFF"
    elif len(positives) >= 3 and not negatives:
        label = "RISK_ON"
    else:
        label = "NEUTRAL"
    return {"label": label, "inputs": inputs, "reasons": positives + negatives}
