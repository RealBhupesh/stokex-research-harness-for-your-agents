"""Audited Upstox V3 daily-candle integration using only read-only requests.

Wire contract: https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/
Availability defaults to retrieval time, not the candle's start timestamp.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote
import urllib.error
import urllib.request
from uuid import uuid4

from ..market.importers import import_market_file
from ..operations import atomic_transaction


API_ROOT = "https://api.upstox.com/v3/historical-candle"
TOKEN_ENV = "UPSTOX_ACCESS_TOKEN"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
IST = timezone(timedelta(hours=5, minutes=30))
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def strict_json(raw):
    def reject(value):
        raise ValueError(f"Non-finite JSON value {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result
    return json.loads(raw, parse_constant=reject, object_pairs_hook=unique)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read(response):
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "Provider response exceeds the size limit")
    return raw


def _transport(url, headers, timeout):
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            return response.status, _read(response), dict(response.headers)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, _read(error), dict(error.headers)


@dataclass(frozen=True)
class Instrument:
    instrument_key: str
    kind: str
    name: str
    isin: str | None = None
    series: str = "EQ"


def validate_instruments(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "instruments"} \
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Provider manifest requires schema_version=1 and instruments")
    items = manifest["instruments"]
    if not isinstance(items, list) or not 1 <= len(items) <= 5000:
        raise ValueError("Provider manifest needs 1–5000 instruments")
    result, keys, names = [], set(), set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"instruments[{index}] must be an object")
        kind = item.get("type")
        expected = {"type", "instrument_key", "symbol", "isin", "series"} if kind == "equity" else \
            {"type", "instrument_key", "index_name"}
        if not isinstance(kind, str) or kind not in {"equity", "index"} or set(item) != expected:
            raise ValueError(f"instruments[{index}] has missing or unsupported fields")
        key = item["instrument_key"]
        if not isinstance(key, str):
            raise ValueError("instrument_key must be a string")
        name = item.get("symbol") if kind == "equity" else item.get("index_name")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Instrument name must be a non-empty string of at most 100 characters")
        name = name.strip().upper()
        if kind == "equity":
            isin = item["isin"]
            if not isinstance(isin, str) or not re.fullmatch(r"IN[A-Z0-9]{9}[0-9]", isin) \
                    or key != "NSE_EQ|" + isin or not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,31}", name):
                raise ValueError("Equity identity requires an NSE_EQ instrument key matching its Indian ISIN and symbol")
            if not isinstance(item["series"], str) or item["series"] not in {"EQ", "BE", "BZ", "SM", "ST"}:
                raise ValueError("Equity series must be explicitly supplied from a verified exchange instrument list")
        else:
            isin = None
            if not key.startswith("NSE_INDEX|") or not key.split("|", 1)[1].strip() \
                    or any(ord(c) < 32 for c in key + name):
                raise ValueError("Index identity requires an explicit NSE_INDEX instrument key and clean index_name")
        if key in keys or (kind, name) in names:
            raise ValueError("Duplicate instrument key or output name in provider manifest")
        keys.add(key)
        names.add((kind, name))
        result.append(Instrument(key, kind, name, isin, item["series"] if kind == "equity" else "EQ"))
    return result


def _number(value, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 1e308 \
            or not math.isfinite(value):
        raise ProviderError("PROVIDER_CANDLE_INVALID", "Candle numbers must be finite JSON numbers")
    if integer and (value < 0 or value > 2 ** 53 - 1 or int(value) != value):
        raise ProviderError("PROVIDER_CANDLE_INVALID", "Candle quantities must be exact non-negative integers no larger than 2^53-1")
    return int(value) if integer else float(value)


def parse_candles(raw, start, end):
    try:
        payload = strict_json(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProviderError("PROVIDER_RESPONSE_INVALID", "Provider returned invalid JSON") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    candles = data.get("candles") if isinstance(data, dict) else None
    if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(candles, list) or not candles:
        raise ProviderError("PROVIDER_RESPONSE_INVALID", "Provider returned no successful daily candles")
    result = {}
    for row in candles:
        if not isinstance(row, list) or len(row) != 7 or not isinstance(row[0], str):
            raise ProviderError("PROVIDER_CANDLE_INVALID", "Expected seven daily candle fields")
        try:
            stamp = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("timezone missing")
            local = stamp.astimezone(IST)
            day = local.date().isoformat()
            if local.time().isoformat() != "00:00:00" or not start <= day <= end:
                raise ValueError("not a daily candle within requested range")
        except ValueError:
            raise ProviderError("PROVIDER_CANDLE_INVALID", "Invalid candle timestamp or requested date range") from None
        o, h, l, c = (_number(value) for value in row[1:5])
        volume, oi = _number(row[5], integer=True), _number(row[6], integer=True)
        if min(o, h, l, c) <= 0 or h < max(o, c, l) or l > min(o, c, h):
            raise ProviderError("PROVIDER_CANDLE_INVALID", "Candle OHLC envelope is inconsistent")
        candle = {"date": day, "open": o, "high": h, "low": l, "close": c, "volume": volume, "oi": oi}
        if day in result and result[day] != candle:
            raise ProviderError("PROVIDER_CANDLE_CONFLICT", "Provider returned conflicting candles for the same day")
        result[day] = candle
    return [result[day] for day in sorted(result)]


class UpstoxClient:
    def __init__(self, token=None, *, timeout=30, transport=None, sleeper=time.sleep, clock=None):
        self._token = token if token is not None else os.environ.get(TOKEN_ENV)
        if not isinstance(self._token, str) or not self._token.strip():
            raise ProviderError("PROVIDER_CONFIG_MISSING", f"Set {TOKEN_ENV} for read-only Upstox market data")
        if any(ord(character) < 33 or ord(character) > 126 for character in self._token):
            raise ProviderError("PROVIDER_CONFIG_INVALID", "Provider token contains invalid header characters")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
                or not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("Provider timeout must be in (0, 120] seconds")
        self.timeout, self._transport, self._sleeper = timeout, transport or _transport, sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def daily(self, instrument, start, end):
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last or (last - first).days > 3650:
            raise ValueError("Daily request must be ordered and span at most 3650 days")
        url = f"{API_ROOT}/{quote(instrument.instrument_key, safe='')}/days/1/{end}/{start}"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        for attempt in range(3):
            try:
                status, raw, response_headers = self._transport(url, headers, self.timeout)
            except OSError:
                if attempt == 2:
                    raise ProviderError("PROVIDER_NETWORK_ERROR", "Provider request failed after three attempts") from None
                self._sleeper(0.5 * 2 ** attempt)
                continue
            if status in RETRY_STATUSES and attempt < 2:
                try:
                    delay = float(next((value for key, value in response_headers.items()
                                        if key.lower() == "retry-after"), 0.5 * 2 ** attempt))
                except (ValueError, TypeError):
                    delay = 0.5 * 2 ** attempt
                self._sleeper(min(5.0, max(0.5, delay)) if math.isfinite(delay) else 1.0)
                continue
            if status != 200:
                raise ProviderError("PROVIDER_HTTP_ERROR", f"Upstox returned HTTP {status}")
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "Provider response exceeds the size limit")
            retrieved = self._clock()
            if retrieved.tzinfo is None:
                raise ValueError("Provider clock must be timezone-aware")
            stamp = retrieved.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            candles = parse_candles(raw, start, end)
            if any(candle["date"] >= retrieved.astimezone(IST).date().isoformat() for candle in candles):
                raise ProviderError("PROVIDER_SESSION_INCOMPLETE", "Only completed prior-day daily candles are accepted")
            return {"url": url, "retrieved_at": stamp, "raw": raw,
                    "sha256": hashlib.sha256(raw).hexdigest(), "candles": candles}
        raise AssertionError("unreachable")


def _new_candles(connection, instrument, candles):
    """Keep first-seen availability immutable; reject later price corrections."""
    new = []
    for candle in candles:
        if instrument.kind == "equity":
            existing = connection.execute(
                "SELECT open, high, low, close, volume, isin FROM bars WHERE symbol=? AND series=? AND trade_date=?",
                (instrument.name, instrument.series, candle["date"]),
            ).fetchone()
            expected = tuple(candle[key] for key in ("open", "high", "low", "close", "volume"))
            if existing is not None and (tuple(existing)[:5] != expected or
                                         existing["isin"] not in (None, instrument.isin)):
                raise ProviderError("PROVIDER_DATA_CONFLICT", "Provider candle conflicts with existing OHLCV or identity")
        else:
            existing = connection.execute(
                "SELECT open, high, low, close FROM index_bars WHERE index_name=? AND trade_date=?",
                (instrument.name, candle["date"]),
            ).fetchone()
            if existing is not None and tuple(existing) != tuple(candle[key] for key in ("open", "high", "low", "close")):
                raise ProviderError("PROVIDER_DATA_CONFLICT", "Provider index candle conflicts with existing OHLC")
        if existing is None:
            new.append(candle)
    return new


def _adapter_file(directory, instrument, candles, number):
    path = directory / f"provider-{number}.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if instrument.kind == "equity":
            writer.writerow(["TradDt", "TckrSymb", "FinInstrmTp", "SctySrs", "ISIN", "OpnPric",
                             "HghPric", "LwPric", "ClsPric", "TtlTradgVol"])
            for candle in candles:
                writer.writerow([candle["date"], instrument.name, "STK", instrument.series, instrument.isin,
                                 *[candle[key] for key in ("open", "high", "low", "close", "volume")]])
            return path, "udiff"
        writer.writerow(["Index Name", "Index Date", "Open Index Value", "High Index Value",
                         "Low Index Value", "Closing Index Value"])
        for candle in candles:
            writer.writerow([instrument.name, candle["date"],
                             *[candle[key] for key in ("open", "high", "low", "close")]])
        return path, "index"


def sync_upstox(connection, manifest, start, end, raw_directory, *, client=None, request_pause=0.2):
    """Fetch and validate every response before atomically publishing a data batch."""
    instruments = validate_instruments(manifest)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 3650:
        raise ValueError("Daily request must be ordered and span at most 3650 days")
    if isinstance(request_pause, bool) or not isinstance(request_pause, (int, float)) \
            or not math.isfinite(request_pause) or request_pause < 0.2:
        raise ValueError("request_pause must be finite and at least 0.2 seconds")
    client = client or UpstoxClient()
    raw_directory = Path(raw_directory)
    raw_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fetched = []
    for index, instrument in enumerate(instruments):
        if index:
            client._sleeper(request_pause)
        response = client.daily(instrument, start, end)
        raw_path = raw_directory / (response["sha256"] + ".json")
        if not raw_path.exists():
            # Preserve the exact response bytes, without request headers or token.
            descriptor, temporary = tempfile.mkstemp(prefix=".provider-", dir=raw_directory)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(response["raw"])
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, raw_path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        elif hashlib.sha256(raw_path.read_bytes()).hexdigest() != response["sha256"]:
            raise ProviderError("PROVIDER_CACHE_CORRUPT", "Cached raw provider response failed its checksum")
        fetched.append((instrument, response, raw_path))
    sync_id = uuid4().hex
    manifest_sha256 = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    summaries = []
    with tempfile.TemporaryDirectory(prefix="stockex-provider-") as temporary:
        with atomic_transaction(connection):
            connection.execute("""CREATE TABLE IF NOT EXISTS provider_downloads (
                sync_id TEXT NOT NULL, instrument_key TEXT NOT NULL, name TEXT NOT NULL,
                request_url TEXT NOT NULL, from_date TEXT NOT NULL, to_date TEXT NOT NULL,
                retrieved_at TEXT NOT NULL, available_at_policy TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL, raw_path TEXT NOT NULL, candles INTEGER NOT NULL,
                inserted INTEGER NOT NULL, price_basis TEXT NOT NULL, manifest_sha256 TEXT NOT NULL,
                PRIMARY KEY(sync_id, instrument_key))""")
            for number, (instrument, response, raw_path) in enumerate(fetched):
                candles = _new_candles(connection, instrument, response["candles"])
                if candles:
                    path, kind = _adapter_file(Path(temporary), instrument, candles, number)
                    imported = import_market_file(connection, path, kind=kind, available_at=response["retrieved_at"])
                    if imported["written"] != len(candles) or imported["skipped"]:
                        raise ProviderError("PROVIDER_IMPORT_INCOMPLETE", "Provider adapter did not import every validated candle")
                connection.execute("INSERT INTO provider_downloads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (sync_id, instrument.instrument_key, instrument.name, response["url"], start, end,
                                    response["retrieved_at"], "RETRIEVED_AT", response["sha256"], str(raw_path.resolve()),
                                    len(response["candles"]), len(candles), "UNVERIFIED_PROVIDER_HISTORY", manifest_sha256))
                summaries.append({"instrument_key": instrument.instrument_key, "name": instrument.name,
                                  "candles": len(response["candles"]), "inserted": len(candles),
                                  "raw_sha256": response["sha256"], "retrieved_at": response["retrieved_at"]})
    report = {"provider": "upstox", "sync_id": sync_id, "from": start, "to": end,
              "availability_policy": "RETRIEVED_AT", "price_basis": "UNVERIFIED_PROVIDER_HISTORY",
              "manifest_sha256": manifest_sha256, "instruments": summaries,
              "limitations": ["Historical candle starts are not publication timestamps.",
                              "Delivery, traded value, corporate actions and restrictions are not supplied.",
                              "Provider adjustment basis is unverified; reconcile against primary corporate-action vintages before adjusted research.",
                              "New history is eligible only after retrieval; use licensed publication vintages for historical tests."]}
    return report
