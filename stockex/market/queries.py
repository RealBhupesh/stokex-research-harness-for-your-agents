"""Point-in-time reads over imported market tables.

Every read takes an ``as_of`` trade date (``YYYY-MM-DD``) and only returns
rows for that date or earlier whose ``available_at`` is no later than the
end-of-day publication time of ``as_of``.
"""

from dataclasses import dataclass, field
import sqlite3

from .corporate import adjustment_events, apply_adjustments
from .importers import DEFAULT_AVAILABLE_TIME_UTC
from ..store.records import normalize_timestamp


SERIES_PREFERENCE = ("EQ", "BE", "BZ", "SM", "ST")


def cutoff(as_of: str, known_at: str | None = None) -> str:
    default = f"{as_of}T{DEFAULT_AVAILABLE_TIME_UTC}Z"
    if known_at is None:
        return default
    normalized = normalize_timestamp(known_at, "known_at")
    if normalized < default:
        raise ValueError("Research cutoff cannot precede the requested session's end-of-day cutoff")
    return normalized


@dataclass
class PriceSeries:
    symbol: str
    dates: list = field(default_factory=list)
    open: list = field(default_factory=list)
    high: list = field(default_factory=list)
    low: list = field(default_factory=list)
    close: list = field(default_factory=list)
    prev_close: list = field(default_factory=list)
    volume: list = field(default_factory=list)
    value: list = field(default_factory=list)
    delivery_qty: list = field(default_factory=list)
    delivery_pct: list = field(default_factory=list)
    series: list = field(default_factory=list)
    adjustments: list = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dates)

    def append(self, row) -> None:
        self.dates.append(row["trade_date"])
        self.open.append(row["open"])
        self.high.append(row["high"])
        self.low.append(row["low"])
        self.close.append(row["close"])
        self.prev_close.append(row["prev_close"])
        self.volume.append(row["volume"])
        value = row["traded_value"]
        self.value.append(value if value is not None else row["close"] * row["volume"])
        self.delivery_qty.append(row["delivery_qty"])
        self.delivery_pct.append(row["delivery_pct"])
        self.series.append(row["series"])

    def truncated(self, length: int) -> "PriceSeries":
        """Return the first ``length`` bars, used to prove no lookahead."""
        result = PriceSeries(self.symbol)
        for name in ("dates", "open", "high", "low", "close", "prev_close", "volume", "value",
                     "delivery_qty", "delivery_pct", "series"):
            setattr(result, name, getattr(self, name)[:length])
        return result


def _rank(series: str) -> int:
    return SERIES_PREFERENCE.index(series) if series in SERIES_PREFERENCE else len(SERIES_PREFERENCE)


def load_histories(
    connection: sqlite3.Connection,
    as_of: str,
    *,
    start: str | None = None,
    symbols: list[str] | None = None,
    adjust: bool = True,
    known_at: str | None = None,
) -> dict[str, PriceSeries]:
    """Load every symbol's bars up to ``as_of``, one bar per date.

    With ``adjust`` (the default) prices before each split, bonus or
    consolidation ex-date on or before ``as_of`` are back-adjusted.
    """
    clauses = ["trade_date <= ?", "available_at <= ?"]
    params: list = [as_of, cutoff(as_of, known_at)]
    if start is not None:
        clauses.append("trade_date >= ?")
        params.append(start)
    if symbols:
        clauses.append(f"symbol IN ({', '.join('?' for _ in symbols)})")
        params.extend(symbol.upper() for symbol in symbols)
    rows = connection.execute(
        f"SELECT * FROM bars WHERE {' AND '.join(clauses)} ORDER BY symbol, trade_date",
        params,
    ).fetchall()
    histories: dict[str, PriceSeries] = {}
    for row in rows:
        series = histories.setdefault(row["symbol"], PriceSeries(row["symbol"]))
        if series.dates and series.dates[-1] == row["trade_date"]:
            if _rank(row["series"]) < _rank(series.series[-1]):
                for name in ("dates", "open", "high", "low", "close", "prev_close", "volume", "value",
                             "delivery_qty", "delivery_pct", "series"):
                    getattr(series, name).pop()
                series.append(row)
            continue
        series.append(row)
    if adjust:
        explicit: dict[str, list] = {}
        for row in connection.execute(
            "SELECT symbol, ex_date, kind, factor FROM corporate_actions WHERE ex_date <= ? AND available_at <= ? ORDER BY ex_date",
            (as_of, cutoff(as_of, known_at)),
        ):
            explicit.setdefault(row["symbol"], []).append(
                {"ex_date": row["ex_date"], "kind": row["kind"], "factor": row["factor"]}
            )
        for symbol, series in histories.items():
            apply_adjustments(series, adjustment_events(series, explicit.get(symbol, [])))
    return histories


def load_history(connection, symbol: str, as_of: str, *, start: str | None = None,
                 adjust: bool = True, known_at: str | None = None) -> PriceSeries:
    return load_histories(connection, as_of, start=start, symbols=[symbol], adjust=adjust, known_at=known_at).get(
        symbol.upper(), PriceSeries(symbol.upper())
    )


def index_closes(connection, index_name: str, as_of: str, *, known_at: str | None = None) -> dict[str, float]:
    rows = connection.execute(
        "SELECT trade_date, close FROM index_bars WHERE index_name = ? AND trade_date <= ? "
        "AND available_at <= ? ORDER BY trade_date",
        (index_name.upper(), as_of, cutoff(as_of, known_at)),
    ).fetchall()
    return {row["trade_date"]: row["close"] for row in rows}


def index_names(connection) -> list[str]:
    return [row[0] for row in connection.execute("SELECT DISTINCT index_name FROM index_bars ORDER BY 1")]


def trading_dates(connection, start: str, end: str) -> list[str]:
    rows = connection.execute(
        "SELECT DISTINCT trade_date FROM bars WHERE trade_date BETWEEN ? AND ? ORDER BY trade_date",
        (start, end),
    ).fetchall()
    return [row[0] for row in rows]


def futures_history(connection, as_of: str, *, symbols: list[str] | None = None, start: str | None = None,
                    known_at: str | None = None) -> dict:
    """Per symbol and date: near-month future price, near-month OI and total futures OI."""
    clauses = ["instrument = 'FUT'", "trade_date <= ?", "available_at <= ?", "expiry >= trade_date"]
    params: list = [as_of, cutoff(as_of, known_at)]
    if start is not None:
        clauses.append("trade_date >= ?")
        params.append(start)
    if symbols:
        clauses.append(f"symbol IN ({', '.join('?' for _ in symbols)})")
        params.extend(symbol.upper() for symbol in symbols)
    rows = connection.execute(
        f"SELECT symbol, trade_date, expiry, close, settle, open_interest, volume FROM fo_bars "
        f"WHERE {' AND '.join(clauses)} ORDER BY symbol, trade_date, expiry",
        params,
    ).fetchall()
    result: dict[str, dict[str, dict]] = {}
    for row in rows:
        by_date = result.setdefault(row["symbol"], {})
        day = by_date.get(row["trade_date"])
        oi = row["open_interest"] or 0
        price = row["close"] if row["close"] else row["settle"]
        if day is None:
            by_date[row["trade_date"]] = {
                "near_expiry": row["expiry"], "near_price": price, "near_oi": oi,
                "next_oi": 0, "total_oi": oi, "volume": row["volume"] or 0,
            }
        else:
            if day["next_oi"] == 0 and row["expiry"] != day["near_expiry"]:
                day["next_oi"] = oi
            day["total_oi"] += oi
            day["volume"] += row["volume"] or 0
    return result


def option_chain(connection, symbol: str, trade_date: str, *, known_at: str | None = None) -> list[dict]:
    """Nearest-expiry option rows for one symbol on one date."""
    expiry = connection.execute(
        "SELECT MIN(expiry) FROM fo_bars WHERE symbol = ? AND trade_date = ? AND instrument IN ('CE', 'PE') "
        "AND expiry >= trade_date AND available_at <= ?",
        (symbol.upper(), trade_date, cutoff(trade_date, known_at)),
    ).fetchone()[0]
    if expiry is None:
        return []
    rows = connection.execute(
        "SELECT instrument, expiry, strike, settle, close, open_interest, underlying FROM fo_bars "
        "WHERE symbol = ? AND trade_date = ? AND expiry = ? AND instrument IN ('CE', 'PE') "
        "AND available_at <= ? ORDER BY strike",
        (symbol.upper(), trade_date, expiry, cutoff(trade_date, known_at)),
    ).fetchall()
    return [dict(row) for row in rows]


def deals_between(connection, start: str, end: str, *, symbol: str | None = None,
                  known_at: str | None = None) -> list[dict]:
    params: list = [start, end, cutoff(end, known_at)]
    clause = ""
    if symbol:
        clause = " AND symbol = ?"
        params.append(symbol.upper())
    rows = connection.execute(
        "SELECT * FROM deals WHERE deal_date BETWEEN ? AND ? AND available_at <= ?" + clause +
        " ORDER BY deal_date, symbol, client",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def restrictions_on(connection, trade_date: str, *, through: str | None = None,
                    known_at: str | None = None) -> dict[str, list[str]]:
    """Lists active on ``trade_date``, plus any starting by ``through`` (e.g. tomorrow's ban list)."""
    rows = connection.execute(
        "SELECT symbol, list_name, stage FROM restrictions WHERE from_date <= ? "
        "AND (to_date IS NULL OR to_date >= ?) AND available_at <= ? ORDER BY symbol, list_name",
        (through or trade_date, trade_date, cutoff(trade_date, known_at)),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        label = row["list_name"] + (f":{row['stage']}" if row["stage"] else "")
        result.setdefault(row["symbol"], []).append(label)
    return result


def sector_map(connection, as_of: str | None = None) -> dict[str, str]:
    """Symbol to industry from the most recent constituent list that names it."""
    clause = " AND as_of_date <= ?" if as_of else ""
    rows = connection.execute(
        "SELECT symbol, industry FROM index_members WHERE industry IS NOT NULL" + clause +
        " ORDER BY as_of_date, index_name, symbol", (as_of,) if as_of else (),
    ).fetchall()
    return {row["symbol"]: row["industry"] for row in rows}


def sector_maps_by_day(connection, days: list[str]) -> dict[str, dict[str, str]]:
    """Advance sector classifications only when their dated snapshots are available."""
    if not days:
        return {}
    rows = iter(connection.execute(
        "SELECT symbol, industry, as_of_date FROM index_members WHERE industry IS NOT NULL "
        "AND as_of_date <= ? ORDER BY as_of_date, index_name, symbol", (max(days),)
    ))
    row = next(rows, None)
    current, result = {}, {}
    for day in sorted(set(days)):
        if row is not None and row["as_of_date"] <= day:
            current = dict(current)
        while row is not None and row["as_of_date"] <= day:
            current[row["symbol"]] = row["industry"]
            row = next(rows, None)
        result[day] = current
    return result


def announcements_between(connection, start: str, end: str, *, known_at: str | None = None) -> dict[str, list[dict]]:
    """Exchange evidence with only model interpretations known by the cutoff.

    Raw categories remain available; model labels carry their own provenance and
    are interpretations, never verified exchange categorizations.
    """
    from ..jev.announcements import announcement_hash

    research_cutoff = cutoff(end, known_at)
    rows = connection.execute(
        "SELECT * FROM announcements WHERE broadcast_at >= ? AND broadcast_at <= ? ORDER BY broadcast_at",
        (f"{start}T00:00:00Z", min(cutoff(end), research_cutoff)),
    ).fetchall()
    annotations = connection.execute(
        "SELECT * FROM announcement_classifications WHERE judged_at <= ? AND broadcast_at >= ? AND broadcast_at <= ? "
        "ORDER BY judged_at DESC, confidence_floor DESC, classification_id DESC",
        (research_cutoff, f"{start}T00:00:00Z", cutoff(end))
    ).fetchall()
    latest = {}
    for annotation in annotations:
        key = (annotation["symbol"], annotation["broadcast_at"], annotation["subject"], annotation["input_sha256"])
        latest.setdefault(key, dict(annotation))
    result: dict[str, list[dict]] = {}
    for row in rows:
        item = dict(row)
        item["raw_category"] = item["category"]
        item["raw_category_source"] = item["category_source"]
        key = (row["symbol"], row["broadcast_at"], row["subject"], announcement_hash(row["subject"], row["details"]))
        annotation = latest.get(key)
        legacy = row["category_source"] in {"JEV", "JEV_LOW_CONFIDENCE"}
        if legacy:
            # Pre-v5 in-place labels have no model or knowledge timestamp.
            item["category"] = "OTHER"
            item["category_source"] = "JEV_LEGACY_UNTIMED"
        if ((row["category"] == "OTHER" and row["category_source"] == "KEYWORD") or legacy) and annotation:
            item["category"] = annotation["applied_category"]
            item["category_source"] = "JEV_INTERPRETATION"
            item["classification"] = annotation
        result.setdefault(row["symbol"], []).append(item)
    return result


def coverage(connection) -> dict:
    def span(table: str, column: str) -> dict:
        row = connection.execute(
            f"SELECT MIN({column}), MAX({column}), COUNT(DISTINCT {column}), COUNT(*) FROM {table}"
        ).fetchone()
        return {"first": row[0], "last": row[1], "dates": row[2], "rows": row[3]}

    bars = span("bars", "trade_date")
    bars["symbols"] = connection.execute("SELECT COUNT(DISTINCT symbol) FROM bars").fetchone()[0]
    bars["with_delivery"] = connection.execute(
        "SELECT COUNT(*) FROM bars WHERE delivery_pct IS NOT NULL"
    ).fetchone()[0]
    missing_delivery_dates = [
        row[0] for row in connection.execute(
            "SELECT trade_date FROM bars GROUP BY trade_date HAVING COUNT(delivery_pct) = 0 ORDER BY trade_date"
        )
    ]
    fo_dates = {row[0] for row in connection.execute("SELECT DISTINCT trade_date FROM fo_bars")}
    bar_dates = {row[0] for row in connection.execute("SELECT DISTINCT trade_date FROM bars")}
    index_dates = {row[0] for row in connection.execute("SELECT DISTINCT trade_date FROM index_bars")}
    return {
        "bars": bars,
        "index_bars": {**span("index_bars", "trade_date"), "indices": index_names(connection)},
        "fo_bars": span("fo_bars", "trade_date"),
        "deals": span("deals", "deal_date"),
        "restrictions": connection.execute("SELECT COUNT(*) FROM restrictions").fetchone()[0],
        "corporate_actions": connection.execute("SELECT COUNT(*) FROM corporate_actions").fetchone()[0],
        "sector_mapped_symbols": connection.execute(
            "SELECT COUNT(DISTINCT symbol) FROM index_members WHERE industry IS NOT NULL").fetchone()[0],
        "announcements": connection.execute("SELECT COUNT(*) FROM announcements").fetchone()[0],
        "journal_entries": connection.execute("SELECT COUNT(*) FROM journal").fetchone()[0],
        "gaps": {
            "dates_without_delivery": missing_delivery_dates,
            "bar_dates_without_index": sorted(bar_dates - index_dates),
            "bar_dates_without_fo": sorted(bar_dates - fo_dates) if fo_dates else "NO_FO_DATA",
        },
    }
