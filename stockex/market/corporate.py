"""Corporate-action price adjustment and announcement classification.

NSE bhavcopies carry raw prices, so a 1:5 split looks like an 80% crash.
Adjustment factors come from two sources:

- the NSE corporate-actions file (``SPLIT``, ``BONUS``, ``CONSOLIDATION``);
- inference from the bhavcopy itself: on an ex-date NSE publishes an adjusted
  ``PREV_CLOSE``, so ``prev_close / previous close`` reveals the factor even
  when the corporate-actions file is missing a row (rights issues included).

Bars before an ex-date are multiplied by the factor (prices) and divided by it
(quantities), so history is comparable with today's share count. Only
ex-dates on or before the query's as-of date are applied.
"""

from datetime import date
import re


INFERENCE_THRESHOLD = 0.02
EXPLICIT_WINDOW_DAYS = 5


def parse_purpose(purpose: str) -> tuple[str, float] | None:
    """Return ``(kind, factor)`` for split/bonus/consolidation text, else ``None``.

    The factor multiplies pre-ex-date prices: a split from Rs 10 to Rs 2 is
    0.2, a 1:1 bonus is 0.5, a consolidation from Rs 1 to Rs 10 is 10.
    """
    text = " ".join((purpose or "").lower().split())
    face = re.search(r"from\s*(?:rs|re|inr)?\.?\s*/?-?\s*([\d.]+).*?to\s*(?:rs|re|inr)?\.?\s*/?-?\s*([\d.]+)", text)
    if ("split" in text or "sub-division" in text or "subdivision" in text) and face:
        old, new = float(face[1]), float(face[2])
        if old > 0 and new > 0 and new < old:
            return "SPLIT", new / old
    if "consolidat" in text and face:
        old, new = float(face[1]), float(face[2])
        if old > 0 and new > old:
            return "CONSOLIDATION", new / old
    bonus = re.search(r"bonus\s*(?:issue)?\s*(\d+)\s*:\s*(\d+)", text)
    if bonus:
        new_shares, held = int(bonus[1]), int(bonus[2])
        if new_shares > 0 and held > 0:
            return "BONUS", held / (new_shares + held)
    return None


def _days_between(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def adjustment_events(series, explicit: list[dict]) -> list[dict]:
    """Explicit plus inferred adjustment events for one price series."""
    events = [dict(event, source="CORPORATE_ACTIONS") for event in explicit]
    for i in range(1, len(series)):
        previous_close, published = series.close[i - 1], series.prev_close[i]
        if not published or not previous_close:
            continue
        ratio = published / previous_close
        if abs(ratio - 1) <= INFERENCE_THRESHOLD:
            continue
        day = series.dates[i]
        if any(_days_between(day, event["ex_date"]) <= EXPLICIT_WINDOW_DAYS for event in explicit):
            continue
        events.append({"ex_date": day, "kind": "INFERRED", "factor": ratio, "source": "PREV_CLOSE"})
    return sorted(events, key=lambda event: event["ex_date"])


def apply_adjustments(series, events: list[dict]) -> None:
    """Back-adjust a ``PriceSeries`` in place for the given events."""
    if not events:
        series.adjustments = []
        return
    n = len(series)
    price_factor = [1.0] * n
    for event in events:
        for i in range(n):
            if series.dates[i] < event["ex_date"]:
                price_factor[i] *= event["factor"]
    for i, factor in enumerate(price_factor):
        if factor == 1.0:
            continue
        for name in ("open", "high", "low", "close"):
            getattr(series, name)[i] *= factor
        if series.prev_close[i] is not None:
            series.prev_close[i] *= factor
        series.volume[i] = int(round(series.volume[i] / factor))
        if series.delivery_qty[i] is not None:
            series.delivery_qty[i] = int(round(series.delivery_qty[i] / factor))
    # The ex-date bar's prev_close is already adjusted by NSE; nothing else to do.
    series.adjustments = [
        {"ex_date": event["ex_date"], "kind": event["kind"], "factor": round(event["factor"], 6),
         "source": event["source"]}
        for event in events
    ]


_CATEGORIES = (
    ("RESULTS", ("financial result", "audited result", "unaudited result", "quarterly result", "results for the")),
    ("BONUS_SPLIT", ("bonus", "split", "sub-division")),
    ("BUYBACK", ("buyback", "buy-back", "buy back")),
    ("DIVIDEND", ("dividend",)),
    ("FUND_RAISE", ("qip", "qualified institutions placement", "preferential", "rights issue", "fund raising")),
    ("PROMOTER_TRADE", ("promoter", "regulation 29", "regulation 7(2)", "acquisition of shares", "pledge")),
    ("CREDIT_RATING", ("credit rating", "rating")),
    ("M_AND_A", ("acquisition", "merger", "amalgamation", "demerger", "scheme of arrangement")),
    ("LITIGATION", ("litigation", "penalty", "sebi order", "show cause", "tribunal", "court order")),
    ("ORDER_WIN", ("order win", "receipt of order", "receipt of an order", "work order", "purchase order",
                   "orders worth", "order worth", "letter of award", "bagged", "secures order", "new order")),
    ("MANAGEMENT_CHANGE", ("resignation", "appointment", "cessation")),
    ("BOARD_MEETING", ("board meeting", "outcome of board")),
)

# Announcement categories that count as a catalyst for an event-driven setup.
CATALYST_CATEGORIES = {"RESULTS", "ORDER_WIN", "BONUS_SPLIT", "BUYBACK", "FUND_RAISE", "PROMOTER_TRADE", "M_AND_A"}


def classify_announcement(subject: str, details: str = "") -> str:
    """Keyword category for an exchange announcement; ``OTHER`` when nothing matches."""
    text = f" {subject} {details} ".lower()
    for category, keywords in _CATEGORIES:
        if any(keyword in text for keyword in keywords):
            return category
    return "OTHER"

