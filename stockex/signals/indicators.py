"""Causal technical features over a daily price series.

Every value at index ``i`` uses bars ``0..i`` only. "Prior" windows exclude
bar ``i`` itself, so a breakout compares today's close with earlier highs.
"""

from collections import deque
from dataclasses import dataclass
import statistics

from ..market.queries import PriceSeries


def sma(values: list, n: int) -> list:
    out, total = [None] * len(values), 0.0
    for i, value in enumerate(values):
        total += value
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def ema(values: list, n: int) -> list:
    out, alpha, current = [None] * len(values), 2 / (n + 1), None
    for i, value in enumerate(values):
        current = value if current is None else alpha * value + (1 - alpha) * current
        if i >= n - 1:
            out[i] = current
    return out


def _rolling_extreme(values: list, n: int, *, prior: bool, maximum: bool) -> list:
    """Rolling max/min over ``n`` bars with a monotonic deque (O(len)).

    With ``prior=True`` the window ends at the previous bar, so index ``i``
    never sees ``values[i]``. Early bars use the shorter history available.
    """
    full = [None] * len(values)
    window: deque = deque()
    for i, value in enumerate(values):
        while window and (values[window[-1]] <= value if maximum else values[window[-1]] >= value):
            window.pop()
        window.append(i)
        if window[0] <= i - n:
            window.popleft()
        full[i] = values[window[0]]
    return [None] + full[:-1] if prior and full else full


def rolling_max(values: list, n: int, *, prior: bool = False) -> list:
    return _rolling_extreme(values, n, prior=prior, maximum=True)


def rolling_min(values: list, n: int, *, prior: bool = False) -> list:
    return _rolling_extreme(values, n, prior=prior, maximum=False)


def rolling_median_prior(values: list, n: int) -> list:
    """Median of the previous ``n`` bars (excluding the current one)."""
    out = [None] * len(values)
    for i in range(n, len(values)):
        out[i] = statistics.median(values[i - n:i])
    return out


def rolling_mean_prior(values: list, n: int, *, min_count: int | None = None) -> list:
    """Mean of the previous ``n`` non-missing values."""
    min_count = n // 2 if min_count is None else min_count
    out = [None] * len(values)
    for i in range(1, len(values)):
        window = [v for v in values[max(0, i - n):i] if v is not None]
        if len(window) >= min_count:
            out[i] = sum(window) / len(window)
    return out


def true_range(high: list, low: list, close: list) -> list:
    out = []
    for i in range(len(close)):
        if i == 0:
            out.append(high[i] - low[i])
        else:
            previous = close[i - 1]
            out.append(max(high[i] - low[i], abs(high[i] - previous), abs(low[i] - previous)))
    return out


def atr(high: list, low: list, close: list, n: int = 14) -> list:
    """Wilder's average true range."""
    ranges = true_range(high, low, close)
    out, current = [None] * len(ranges), None
    for i, value in enumerate(ranges):
        if i < n - 1:
            continue
        if current is None:
            current = sum(ranges[:n]) / n
        else:
            current = (current * (n - 1) + value) / n
        out[i] = current
    return out


def pct_change(values: list, n: int) -> list:
    return [None if i < n or not values[i - n] else values[i] / values[i - n] - 1 for i in range(len(values))]


def aligned_return(dates: list, closes_by_date: dict, n: int) -> list:
    """Benchmark return over the same ``n``-bar window as the stock series."""
    out = [None] * len(dates)
    for i in range(n, len(dates)):
        start, end = closes_by_date.get(dates[i - n]), closes_by_date.get(dates[i])
        if start and end:
            out[i] = end / start - 1
    return out


RETURN_WINDOWS = (1, 5, 20, 60, 120, 250)


@dataclass
class Features:
    symbol: str
    series: PriceSeries
    columns: dict

    def __len__(self) -> int:
        return len(self.series)

    def at(self, i: int) -> dict:
        return {name: values[i] for name, values in self.columns.items()}

    def index_of(self, trade_date: str) -> int | None:
        index = self._date_index().get(trade_date)
        return index

    def _date_index(self) -> dict:
        cached = getattr(self, "_dates", None)
        if cached is None:
            cached = {day: i for i, day in enumerate(self.series.dates)}
            self._dates = cached
        return cached


def compute_features(series: PriceSeries, benchmark: dict | None = None) -> Features:
    s = series
    n = len(s)
    close, high, low, volume = s.close, s.high, s.low, s.volume
    atr14, atr50 = atr(high, low, close, 14), atr(high, low, close, 50)
    columns: dict = {
        "sma20": sma(close, 20), "sma50": sma(close, 50), "sma200": sma(close, 200),
        "ema20": ema(close, 20),
        "atr14": atr14,
        "atr_pct": [None if a is None else a / c for a, c in zip(atr14, close)],
        "atr_contraction": [None if a is None or b is None or not b else a / b for a, b in zip(atr14, atr50)],
        "prior_high5": rolling_max(high, 5, prior=True),
        "prior_high20": rolling_max(high, 20, prior=True),
        "prior_high50": rolling_max(high, 50, prior=True),
        "prior_high252": rolling_max(high, 252, prior=True),
        "prior_low5": rolling_min(low, 5, prior=True),
        "prior_low10": rolling_min(low, 10, prior=True),
        "prior_low20": rolling_min(low, 20, prior=True),
        "high252": rolling_max(high, 252),
        "low252": rolling_min(low, 252),
        "vol_med20": rolling_median_prior(volume, 20),
        "value_med20": rolling_median_prior(s.value, 20),
        "deliv_avg20": rolling_mean_prior(s.delivery_pct, 20),
    }
    for window in RETURN_WINDOWS:
        columns[f"ret{window}"] = pct_change(close, window)
        if benchmark:
            bench = aligned_return(s.dates, benchmark, window)
            columns[f"bench_ret{window}"] = bench
            columns[f"rs{window}"] = [
                None if a is None or b is None else a - b for a, b in zip(columns[f"ret{window}"], bench)
            ]
        else:
            columns[f"bench_ret{window}"] = [None] * n
            columns[f"rs{window}"] = [None] * n

    ranges = [h - l for h, l in zip(high, low)]
    columns["nr7"] = [i >= 6 and ranges[i] == min(ranges[i - 6:i + 1]) for i in range(n)]
    columns["close_position"] = [
        (c - l) / (h - l) if h > l else 1.0 for c, h, l in zip(close, high, low)
    ]
    columns["gap_pct"] = [None if i == 0 else s.open[i] / close[i - 1] - 1 for i in range(n)]
    columns["vol_ratio"] = [
        None if m is None or not m else v / m for v, m in zip(volume, columns["vol_med20"])
    ]
    columns["deliv_ratio"] = [
        None if d is None or a is None or not a else d / a
        for d, a in zip(s.delivery_pct, columns["deliv_avg20"])
    ]
    base_high, base_low = columns["prior_high20"], columns["prior_low20"]
    columns["base_range20"] = [
        None if h is None or lo is None or i == 0 else (h - lo) / close[i - 1]
        for i, (h, lo) in enumerate(zip(base_high, base_low))
    ]
    return Features(series.symbol, series, columns)
