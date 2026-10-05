"""Point-in-time reads over imported market tables.

Every read takes an ``as_of`` trade date (``YYYY-MM-DD``) and only returns
rows for that date or earlier whose ``available_at`` is no later than the
end-of-day publication time of ``as_of``.
"""

from dataclasses import dataclass, field
import sqlite3

from .importers import DEFAULT_AVAILABLE_TIME_UTC


SERIES_PREFERENCE = ("EQ", "BE", "BZ", "SM", "ST")


def cutoff(as_of: str) -> str:
    return f"{as_of}T{DEFAULT_AVAILABLE_TIME_UTC}Z"


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
) -> dict[str, PriceSeries]:
    """Load every symbol's bars up to ``as_of``, one bar per date."""
    clauses = ["trade_date <= ?", "available_at <= ?"]
    params: list = [as_of, cutoff(as_of)]
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
    return histories


def load_history(connection, symbol: str, as_of: str, *, start: str | None = None) -> PriceSeries:
    return load_histories(connection, as_of, start=start, symbols=[symbol]).get(
        symbol.upper(), PriceSeries(symbol.upper())
    )


def index_closes(connection, index_name: str, as_of: str) -> dict[str, float]:
    rows = connection.execute(
        "SELECT trade_date, close FROM index_bars WHERE index_name = ? AND trade_date <= ? "
        "AND available_at <= ? ORDER BY trade_date",
        (index_name.upper(), as_of, cutoff(as_of)),
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


def futures_history(connection, as_of: str, *, symbols: list[str] | None = None, start: str | None = None) -> dict:
    """Per symbol and date: near-month future price, near-month OI and total futures OI."""
    clauses = ["instrument = 'FUT'", "trade_date <= ?", "available_at <= ?", "expiry >= trade_date"]
    params: list = [as_of, cutoff(as_of)]
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


def option_chain(connection, symbol: str, trade_date: str) -> list[dict]:
    """Nearest-expiry option rows for one symbol on one date."""
    expiry = connection.execute(
        "SELECT MIN(expiry) FROM fo_bars WHERE symbol = ? AND trade_date = ? AND instrument IN ('CE', 'PE') "
        "AND expiry >= trade_date AND available_at <= ?",
        (symbol.upper(), trade_date, cutoff(trade_date)),
    ).fetchone()[0]
    if expiry is None:
        return []
    rows = connection.execute(
        "SELECT instrument, expiry, strike, settle, close, open_interest, underlying FROM fo_bars "
        "WHERE symbol = ? AND trade_date = ? AND expiry = ? AND instrument IN ('CE', 'PE') ORDER BY strike",
        (symbol.upper(), trade_date, expiry),
    ).fetchall()
    return [dict(row) for row in rows]


def deals_between(connection, start: str, end: str, *, symbol: str | None = None) -> list[dict]:
    params: list = [start, end, cutoff(end)]
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


def restrictions_on(connection, trade_date: str, *, through: str | None = None) -> dict[str, list[str]]:
    """Lists active on ``trade_date``, plus any starting by ``through`` (e.g. tomorrow's ban list)."""
    rows = connection.execute(
        "SELECT symbol, list_name, stage FROM restrictions WHERE from_date <= ? "
        "AND (to_date IS NULL OR to_date >= ?) ORDER BY symbol, list_name",
        (through or trade_date, trade_date),
    ).fetchall()
    result: dict[str, list[str]] = {}
    for row in rows:
        label = row["list_name"] + (f":{row['stage']}" if row["stage"] else "")
        result.setdefault(row["symbol"], []).append(label)
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
        "gaps": {
            "dates_without_delivery": missing_delivery_dates,
            "bar_dates_without_index": sorted(bar_dates - index_dates),
            "bar_dates_without_fo": sorted(bar_dates - fo_dates) if fo_dates else "NO_FO_DATA",
        },
    }
