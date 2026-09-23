"""Atomic importers for NSE end-of-day CSV files.

Supported inputs (downloaded by the user or an agent's browser; nothing here
fetches from the network):

- ``cm-full``: ``sec_bhavdata_full_DDMMYYYY.csv`` cash bhavcopy with delivery.
- ``udiff``: ``BhavCopy_NSE_CM_*`` / ``BhavCopy_NSE_FO_*`` UDiFF bhavcopies.
- ``index``: ``ind_close_all_DDMMYYYY.csv`` index closing values.
- ``bulk`` / ``block``: bulk and block deal CSVs.
- ``fo-ban``: ``fo_secban_DDMMYYYY.csv`` F&O ban list.
- ``restrictions``: ``list,symbol,stage,from_date,to_date`` rows for
  ASM/GSM or other lists the user maintains.

Column matching ignores case, spaces and punctuation so NSE's padded headers
work. Structural problems (missing columns, unparseable dates or numbers) fail
the whole file with a line number; implausible rows are skipped and counted.
"""

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import io
from pathlib import Path
import re
import sqlite3

from ..store.records import StoreValidationError, normalize_timestamp


KINDS = ("cm-full", "udiff", "index", "bulk", "block", "fo-ban", "restrictions")
DEFAULT_SERIES = frozenset({"EQ", "BE", "BZ", "SM", "ST"})
# Options are only used for the scan-day chain (PCR, IV, OI walls); keep them small.
DEFAULT_OPTION_EXPIRIES = 1
# NSE end-of-day files are normally published by the evening; 18:30 IST.
DEFAULT_AVAILABLE_TIME_UTC = "13:00:00"
_MISSING = {"", "-", "NA", "N/A", "NIL", "NULL"}
_MONTHS = {name: index for index, name in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


@dataclass
class MarketImportError(Exception):
    path: str
    line: int
    code: str
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


class _RowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_date(value: str) -> str:
    """Return ISO ``YYYY-MM-DD`` for NSE date spellings."""
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        year, month, day = map(int, match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ](\d{4})", text)
        if match:
            day, month, year = int(match[1]), _MONTHS.get(match[2].upper()), int(match[3])
            if month is None:
                raise _RowError("DATE_INVALID", f"Unknown month in date {value!r}")
        else:
            match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)
            if not match:
                raise _RowError("DATE_INVALID", f"Unrecognised date {value!r}")
            day, month, year = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError as error:
        raise _RowError("DATE_INVALID", f"Invalid date {value!r}: {error}") from error


def _number(value: str | None, *, integer: bool = False, required: bool = False, name: str = "value"):
    text = (value or "").strip().replace(",", "")
    if text.upper() in _MISSING:
        if required:
            raise _RowError("NUMBER_MISSING", f"{name} is required")
        return None
    try:
        number = float(text)
    except ValueError as error:
        raise _RowError("NUMBER_INVALID", f"{name} is not a number: {value!r}") from error
    if number != number or number in (float("inf"), float("-inf")):
        raise _RowError("NUMBER_INVALID", f"{name} must be finite")
    return int(round(number)) if integer else number


def _available_at(trade_date: str, override: str | None) -> str:
    if override is not None:
        return override
    return f"{trade_date}T{DEFAULT_AVAILABLE_TIME_UTC}Z"


class _Rows:
    """Header-normalised CSV row access with alias lookup."""

    def __init__(self, text: str):
        reader = csv.reader(io.StringIO(text))
        try:
            header = next(reader)
        except StopIteration:
            raise _RowError("FILE_EMPTY", "File has no header row") from None
        self.header = [_key(column) for column in header]
        self.index = {name: position for position, name in enumerate(self.header) if name}
        self.reader = reader

    def has(self, *names: str) -> bool:
        return all(_key(name) in self.index for name in names)

    def require(self, *names: str) -> None:
        missing = [name for name in names if _key(name) not in self.index]
        if missing:
            raise _RowError("COLUMNS_MISSING", f"Missing columns: {', '.join(missing)}")

    def __iter__(self):
        for line_number, row in enumerate(self.reader, 2):
            if not any(cell.strip() for cell in row):
                continue
            yield line_number, row

    def get(self, row: list[str], *aliases: str) -> str | None:
        for alias in aliases:
            position = self.index.get(_key(alias))
            if position is not None and position < len(row):
                return row[position].strip()
        return None


def detect_kind(path: Path, text: str) -> str:
    first_line = text.lstrip("\ufeff").splitlines()[0] if text.strip() else ""
    if first_line.lower().startswith("securities in ban"):
        return "fo-ban"
    header = {_key(column) for column in next(csv.reader(io.StringIO(first_line)), [])}
    if {"symbol", "series", "date1", "closeprice"} <= header:
        return "cm-full"
    if {"traddt", "tckrsymb", "fininstrmtp", "clspric"} <= header:
        return "udiff"
    if {"indexname", "indexdate", "closingindexvalue"} <= header:
        return "index"
    if {"symbol", "clientname", "buysell"} <= header:
        return "block" if "block" in path.name.lower() else "bulk"
    if {"list", "symbol", "fromdate"} <= header:
        return "restrictions"
    raise _RowError("KIND_UNKNOWN", "Could not detect the NSE file kind; pass --kind")


def _import_cm_full(connection, rows: _Rows, context) -> None:
    rows.require("SYMBOL", "SERIES", "DATE1", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE",
                 "CLOSE_PRICE", "TTL_TRD_QNTY")
    for line, row in rows:
        context.line = line
        series = rows.get(row, "SERIES").upper()
        if series not in context.series:
            context.skip("SERIES_EXCLUDED")
            continue
        trade_date = parse_date(rows.get(row, "DATE1"))
        turnover_lacs = _number(rows.get(row, "TURNOVER_LACS"), name="TURNOVER_LACS")
        context.bar(connection, {
            "symbol": rows.get(row, "SYMBOL").upper(),
            "series": series,
            "trade_date": trade_date,
            "open": _number(rows.get(row, "OPEN_PRICE"), required=True, name="OPEN_PRICE"),
            "high": _number(rows.get(row, "HIGH_PRICE"), required=True, name="HIGH_PRICE"),
            "low": _number(rows.get(row, "LOW_PRICE"), required=True, name="LOW_PRICE"),
            "close": _number(rows.get(row, "CLOSE_PRICE"), required=True, name="CLOSE_PRICE"),
            "prev_close": _number(rows.get(row, "PREV_CLOSE"), name="PREV_CLOSE"),
            "volume": _number(rows.get(row, "TTL_TRD_QNTY"), integer=True, required=True, name="TTL_TRD_QNTY"),
            "traded_value": turnover_lacs * 100_000 if turnover_lacs is not None else None,
            "trades": _number(rows.get(row, "NO_OF_TRADES"), integer=True, name="NO_OF_TRADES"),
            "delivery_qty": _number(rows.get(row, "DELIV_QTY"), integer=True, name="DELIV_QTY"),
            "delivery_pct": _number(rows.get(row, "DELIV_PER"), name="DELIV_PER"),
            "isin": None,
        })


def _import_udiff(connection, rows: _Rows, context) -> None:
    rows.require("TradDt", "FinInstrmTp", "TckrSymb", "OpnPric", "HghPric", "LwPric", "ClsPric")
    options = defaultdict(list)
    for line, row in rows:
        context.line = line
        instrument_type = rows.get(row, "FinInstrmTp").upper()
        trade_date = parse_date(rows.get(row, "TradDt"))
        symbol = rows.get(row, "TckrSymb").upper()
        if instrument_type == "STK":
            series = (rows.get(row, "SctySrs") or "").upper()
            if series not in context.series:
                context.skip("SERIES_EXCLUDED")
                continue
            context.bar(connection, {
                "symbol": symbol,
                "series": series,
                "trade_date": trade_date,
                "open": _number(rows.get(row, "OpnPric"), required=True, name="OpnPric"),
                "high": _number(rows.get(row, "HghPric"), required=True, name="HghPric"),
                "low": _number(rows.get(row, "LwPric"), required=True, name="LwPric"),
                "close": _number(rows.get(row, "ClsPric"), required=True, name="ClsPric"),
                "prev_close": _number(rows.get(row, "PrvsClsgPric"), name="PrvsClsgPric"),
                "volume": _number(rows.get(row, "TtlTradgVol"), integer=True, required=True, name="TtlTradgVol"),
                "traded_value": _number(rows.get(row, "TtlTrfVal"), name="TtlTrfVal"),
                "trades": _number(rows.get(row, "TtlNbOfTxsExctd"), integer=True, name="TtlNbOfTxsExctd"),
                "delivery_qty": None,
                "delivery_pct": None,
                "isin": rows.get(row, "ISIN") or None,
            })
            continue
        if instrument_type not in {"STF", "STO", "IDF", "IDO"}:
            context.skip("INSTRUMENT_EXCLUDED")
            continue
        is_option = instrument_type in {"STO", "IDO"}
        instrument = (rows.get(row, "OptnTp") or "").upper() if is_option else "FUT"
        if instrument not in {"FUT", "CE", "PE"}:
            raise _RowError("OPTION_TYPE_INVALID", f"Unknown option type {instrument!r}")
        record = {
            "symbol": symbol,
            "instrument": instrument,
            "expiry": parse_date(rows.get(row, "XpryDt", "FininstrmActlXpryDt")),
            "strike": (_number(rows.get(row, "StrkPric"), name="StrkPric") or 0.0) if is_option else 0.0,
            "trade_date": trade_date,
            "open": _number(rows.get(row, "OpnPric"), name="OpnPric"),
            "high": _number(rows.get(row, "HghPric"), name="HghPric"),
            "low": _number(rows.get(row, "LwPric"), name="LwPric"),
            "close": _number(rows.get(row, "ClsPric"), name="ClsPric"),
            "settle": _number(rows.get(row, "SttlmPric"), name="SttlmPric"),
            "underlying": _number(rows.get(row, "UndrlygPric"), name="UndrlygPric"),
            "open_interest": _number(rows.get(row, "OpnIntrst"), integer=True, name="OpnIntrst"),
            "oi_change": _number(rows.get(row, "ChngInOpnIntrst"), integer=True, name="ChngInOpnIntrst"),
            "volume": _number(rows.get(row, "TtlTradgVol"), integer=True, name="TtlTradgVol"),
            "is_index": 1 if instrument_type.startswith("ID") else 0,
        }
        if is_option:
            options[(symbol, trade_date)].append(record)
        else:
            context.fo(connection, record)
    # Keep options for the nearest expiries only; far months are thin and large.
    for records in options.values():
        expiries = sorted({record["expiry"] for record in records})
        keep = set(expiries if context.option_expiries is None else expiries[:context.option_expiries])
        if not keep:
            context.skipped["OPTIONS_EXCLUDED"] += len(records)
            continue
        for record in records:
            if record["expiry"] in keep:
                context.fo(connection, record)
            else:
                context.skip("OPTION_EXPIRY_EXCLUDED")


def _import_index(connection, rows: _Rows, context) -> None:
    rows.require("Index Name", "Index Date", "Closing Index Value")
    for line, row in rows:
        context.line = line
        trade_date = parse_date(rows.get(row, "Index Date"))
        close = _number(rows.get(row, "Closing Index Value"), name="Closing Index Value")
        if close is None or close <= 0:
            context.skip("CLOSE_MISSING")
            continue
        connection.execute(
            "INSERT OR REPLACE INTO index_bars VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                rows.get(row, "Index Name").strip().upper(), trade_date,
                _number(rows.get(row, "Open Index Value"), name="Open Index Value"),
                _number(rows.get(row, "High Index Value"), name="High Index Value"),
                _number(rows.get(row, "Low Index Value"), name="Low Index Value"),
                close, _available_at(trade_date, context.available_at),
            ),
        )
        context.written += 1


def _import_deals(kind: str):
    def importer(connection, rows: _Rows, context) -> None:
        rows.require("Date", "Symbol", "Client Name", "Buy/Sell", "Quantity Traded")
        for line, row in rows:
            context.line = line
            deal_date = parse_date(rows.get(row, "Date"))
            side = rows.get(row, "Buy/Sell").upper()
            side = {"B": "BUY", "S": "SELL"}.get(side, side)
            if side not in {"BUY", "SELL"}:
                raise _RowError("SIDE_INVALID", f"Buy/Sell must be BUY or SELL, got {side!r}")
            price = _number(
                rows.get(row, "Trade Price / Wght. Avg. Price", "Trade Price", "Price"),
                required=True, name="Trade Price",
            )
            cursor = connection.execute(
                "INSERT OR IGNORE INTO deals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kind, deal_date, rows.get(row, "Symbol").upper(),
                    " ".join(rows.get(row, "Client Name").split()).upper(), side,
                    _number(rows.get(row, "Quantity Traded"), integer=True, required=True, name="Quantity Traded"),
                    price, _available_at(deal_date, context.available_at),
                ),
            )
            context.written += cursor.rowcount
    return importer


def _import_fo_ban(connection, text: str, context) -> None:
    lines = text.lstrip("\ufeff").splitlines()
    match = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", lines[0])
    if not match:
        context.line = 1
        raise _RowError("DATE_INVALID", "Ban list header has no trade date")
    trade_date = parse_date(match[1])
    for line_number, line in enumerate(lines[1:], 2):
        context.line = line_number
        cells = [cell.strip() for cell in line.split(",") if cell.strip()]
        if not cells:
            continue
        symbol = cells[-1].upper()
        connection.execute(
            "INSERT OR REPLACE INTO restrictions VALUES ('FO_BAN', ?, NULL, ?, ?)",
            (symbol, trade_date, trade_date),
        )
        context.written += 1


def _import_restrictions(connection, rows: _Rows, context) -> None:
    rows.require("list", "symbol", "from_date")
    for line, row in rows:
        context.line = line
        to_date = rows.get(row, "to_date")
        connection.execute(
            "INSERT OR REPLACE INTO restrictions VALUES (?, ?, ?, ?, ?)",
            (
                rows.get(row, "list").upper(), rows.get(row, "symbol").upper(),
                (rows.get(row, "stage") or None),
                parse_date(rows.get(row, "from_date")),
                parse_date(to_date) if to_date else None,
            ),
        )
        context.written += 1


class _Context:
    def __init__(self, series, option_expiries, available_at):
        self.series, self.option_expiries, self.available_at = series, option_expiries, available_at
        self.line = 1
        self.written = 0
        self.skipped = Counter()

    def skip(self, reason: str) -> None:
        self.skipped[reason] += 1

    def bar(self, connection, bar: dict) -> None:
        if min(bar["open"], bar["high"], bar["low"], bar["close"]) <= 0 or bar["high"] < bar["low"]:
            self.skip("PRICE_IMPLAUSIBLE")
            return
        if bar["volume"] < 0:
            self.skip("VOLUME_NEGATIVE")
            return
        bar["available_at"] = _available_at(bar["trade_date"], self.available_at)
        connection.execute(
            """
            INSERT INTO bars (symbol, series, trade_date, open, high, low, close, prev_close, volume,
                              traded_value, trades, delivery_qty, delivery_pct, isin, available_at)
            VALUES (:symbol, :series, :trade_date, :open, :high, :low, :close, :prev_close, :volume,
                    :traded_value, :trades, :delivery_qty, :delivery_pct, :isin, :available_at)
            ON CONFLICT (symbol, series, trade_date) DO UPDATE SET
                delivery_qty = COALESCE(excluded.delivery_qty, bars.delivery_qty),
                delivery_pct = COALESCE(excluded.delivery_pct, bars.delivery_pct),
                isin = COALESCE(excluded.isin, bars.isin),
                traded_value = COALESCE(bars.traded_value, excluded.traded_value),
                trades = COALESCE(bars.trades, excluded.trades),
                prev_close = COALESCE(bars.prev_close, excluded.prev_close)
            """,
            bar,
        )
        self.written += 1

    def fo(self, connection, record: dict) -> None:
        record["available_at"] = _available_at(record["trade_date"], self.available_at)
        connection.execute(
            """
            INSERT OR REPLACE INTO fo_bars (symbol, instrument, expiry, strike, trade_date, open, high, low,
                close, settle, underlying, open_interest, oi_change, volume, is_index, available_at)
            VALUES (:symbol, :instrument, :expiry, :strike, :trade_date, :open, :high, :low, :close, :settle,
                :underlying, :open_interest, :oi_change, :volume, :is_index, :available_at)
            """,
            record,
        )
        self.written += 1


_IMPORTERS = {
    "cm-full": _import_cm_full,
    "udiff": _import_udiff,
    "index": _import_index,
    "bulk": _import_deals("BULK"),
    "block": _import_deals("BLOCK"),
    "restrictions": _import_restrictions,
}


def import_market_file(
    connection: sqlite3.Connection,
    path,
    *,
    kind: str = "auto",
    series=DEFAULT_SERIES,
    option_expiries: int | None = DEFAULT_OPTION_EXPIRIES,
    available_at: str | None = None,
) -> dict:
    """Import one NSE file atomically and return a summary."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        if available_at is not None:
            available_at = normalize_timestamp(available_at, "available_at")
        detected = detect_kind(path, text) if kind == "auto" else kind
        if detected not in KINDS:
            raise _RowError("KIND_UNKNOWN", f"Unknown kind {kind!r}; expected one of {', '.join(KINDS)}")
    except (_RowError, StoreValidationError) as error:
        raise MarketImportError(str(path), 1, error.code, error.message) from None

    if connection.execute("SELECT 1 FROM market_imports WHERE sha256 = ?", (digest,)).fetchone():
        return {"path": str(path), "kind": detected, "status": "unchanged", "written": 0, "skipped": {}}

    context = _Context(frozenset(s.upper() for s in series), option_expiries, available_at)
    try:
        with connection:
            if detected == "fo-ban":
                _import_fo_ban(connection, text, context)
            else:
                _IMPORTERS[detected](connection, _Rows(text), context)
            connection.execute(
                "INSERT INTO market_imports VALUES (?, ?, ?, ?, ?)",
                (digest, detected, str(path), context.written,
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
    except _RowError as error:
        raise MarketImportError(str(path), context.line, error.code, error.message) from None
    except sqlite3.IntegrityError as error:
        raise MarketImportError(str(path), context.line, "ROW_CONSTRAINT", str(error)) from None
    return {
        "path": str(path),
        "kind": detected,
        "status": "imported",
        "written": context.written,
        "skipped": dict(sorted(context.skipped.items())),
    }

