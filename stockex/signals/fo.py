"""F&O positioning signals used only to find and time cash-equity trades."""

from datetime import date
import math


QUADRANTS = ("LONG_BUILDUP", "SHORT_BUILDUP", "SHORT_COVERING", "LONG_UNWINDING", "NEUTRAL")


def oi_quadrant(price_change: float | None, oi_change: float | None, *,
                price_threshold: float = 0.005, oi_threshold: float = 0.02) -> str:
    """Classic price x open-interest reading for one session."""
    if price_change is None or oi_change is None:
        return "NEUTRAL"
    if abs(price_change) < price_threshold or abs(oi_change) < oi_threshold:
        return "NEUTRAL"
    if price_change > 0:
        return "LONG_BUILDUP" if oi_change > 0 else "SHORT_COVERING"
    return "SHORT_BUILDUP" if oi_change > 0 else "LONG_UNWINDING"


def fo_features(dates: list, futures_by_date: dict | None) -> dict:
    """Per-bar futures features aligned to a stock's trading dates.

    ``futures_by_date`` is one symbol's entry from
    ``stockex.market.queries.futures_history``. Missing F&O data yields
    ``None`` values and an ``in_fo`` flag of ``False``.
    """
    n = len(dates)
    columns = {name: [None] * n for name in (
        "fut_price", "total_oi", "oi_chg1", "oi_chg5", "fut_ret1", "rollover", "days_to_expiry",
    )}
    columns["in_fo"] = [False] * n
    columns["quadrant"] = ["NEUTRAL"] * n
    if not futures_by_date:
        return columns
    for i, day in enumerate(dates):
        row = futures_by_date.get(day)
        if row is None:
            continue
        columns["in_fo"][i] = True
        columns["fut_price"][i] = row["near_price"]
        columns["total_oi"][i] = row["total_oi"]
        pair = row["near_oi"] + row["next_oi"]
        columns["rollover"][i] = row["next_oi"] / pair if pair else None
        columns["days_to_expiry"][i] = (date.fromisoformat(row["near_expiry"]) - date.fromisoformat(day)).days
        for lag, name in ((1, "oi_chg1"), (5, "oi_chg5")):
            if i >= lag:
                previous = futures_by_date.get(dates[i - lag])
                if previous and previous["total_oi"]:
                    columns[name][i] = row["total_oi"] / previous["total_oi"] - 1
        if i >= 1:
            previous = futures_by_date.get(dates[i - 1])
            if previous and previous["near_price"] and row["near_price"]:
                columns["fut_ret1"][i] = row["near_price"] / previous["near_price"] - 1
        columns["quadrant"][i] = oi_quadrant(columns["fut_ret1"][i], columns["oi_chg1"][i])
    return columns


def put_call_ratio(chain: list[dict]) -> float | None:
    calls = sum(row["open_interest"] or 0 for row in chain if row["instrument"] == "CE")
    puts = sum(row["open_interest"] or 0 for row in chain if row["instrument"] == "PE")
    return puts / calls if calls else None


def max_oi_strikes(chain: list[dict]) -> dict:
    """Highest-OI call strike (overhead supply) and put strike (support context)."""
    result = {"call_wall": None, "put_wall": None}
    for option, key in (("CE", "call_wall"), ("PE", "put_wall")):
        rows = [row for row in chain if row["instrument"] == option and row["open_interest"]]
        if rows:
            result[key] = max(rows, key=lambda row: row["open_interest"])["strike"]
    return result


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(option: str, spot: float, strike: float, years: float, vol: float, rate: float = 0.065) -> float:
    """Black-Scholes European price on spot (index/stock options are European in India)."""
    if years <= 0 or vol <= 0:
        intrinsic = spot - strike if option == "CE" else strike - spot
        return max(intrinsic, 0.0)
    root = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2) * years) / root
    d2 = d1 - root
    if option == "CE":
        return spot * _norm_cdf(d1) - strike * math.exp(-rate * years) * _norm_cdf(d2)
    return strike * math.exp(-rate * years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def implied_vol(option: str, price: float, spot: float, strike: float, years: float,
                rate: float = 0.065) -> float | None:
    """Bisection implied volatility; ``None`` when the price is outside model bounds."""
    if price is None or price <= 0 or years <= 0:
        return None
    low, high = 1e-4, 5.0
    if not bs_price(option, spot, strike, years, low, rate) <= price <= bs_price(option, spot, strike, years, high, rate):
        return None
    for _ in range(100):
        middle = (low + high) / 2
        if bs_price(option, spot, strike, years, middle, rate) > price:
            high = middle
        else:
            low = middle
        if high - low < 1e-6:
            break
    return (low + high) / 2


def atm_iv(chain: list[dict], trade_date: str, rate: float = 0.065) -> float | None:
    """Average call/put implied volatility at the strike nearest the underlying."""
    rows = [row for row in chain if row.get("underlying")]
    if not rows:
        return None
    spot = rows[0]["underlying"]
    strike = min({row["strike"] for row in rows}, key=lambda value: abs(value - spot))
    years = (date.fromisoformat(rows[0]["expiry"]) - date.fromisoformat(trade_date)).days / 365
    vols = []
    for row in rows:
        if row["strike"] == strike:
            price = row["settle"] or row["close"]
            vol = implied_vol(row["instrument"], price, spot, strike, years, rate)
            if vol is not None:
                vols.append(vol)
    return sum(vols) / len(vols) if vols else None


def option_context(chain: list[dict], trade_date: str) -> dict:
    return {"pcr": put_call_ratio(chain), **max_oi_strikes(chain), "atm_iv": atm_iv(chain, trade_date)}
