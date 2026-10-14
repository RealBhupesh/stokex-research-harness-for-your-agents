"""Match downloaded candle vintages to retained supplied raw NSE files.

Receipts prove exact agreement with supplied inputs, not source authenticity or
the provider's adjustment policy outside the matched dates.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import urlsplit

from ..operations import atomic_transaction, backup_database
from ..market.schema import open_market_db
from ..market.importers import import_market_file
from .upstox import MAX_RESPONSE_BYTES, ProviderError, parse_candles, strict_json, validate_instruments


EXCHANGE_HOSTS = {"nseindia.com", "www.nseindia.com", "nsearchives.nseindia.com", "archives.nseindia.com"}


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reference_imports(connection, database):
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_downloads'").fetchone():
        raise ValueError("Reference database must contain supplied raw exchange files, not provider downloads")
    rows = connection.execute("SELECT sha256, kind, path FROM market_imports WHERE kind IN ('cm-full','udiff','index') ORDER BY sha256").fetchall()
    if not rows:
        raise ValueError("Reference database has no supported raw exchange import provenance")
    records = []
    for row in rows:
        path = Path(row["path"])
        if not path.is_file() and not path.is_absolute():
            path = Path(database).resolve().parent / path
        if not path.is_file() or _file_hash(path) != row["sha256"]:
            raise ProviderError("REFERENCE_SOURCE_UNAVAILABLE", "Retained raw reference files must exist and match their import hashes")
        records.append({"sha256": row["sha256"], "kind": row["kind"], "path": str(path.resolve())})
    return records


def _matches(connection, identity, candle, verified_at):
    expected = tuple(candle[key] for key in ("open", "high", "low", "close"))
    if identity.kind == "equity":
        row = connection.execute(
            "SELECT open,high,low,close,volume,isin FROM bars WHERE symbol=? AND trade_date=? AND isin=? AND series=? AND available_at <= ?",
            (identity.name, candle["date"], identity.isin, identity.series, verified_at),
        ).fetchone()
        return row is not None and tuple(row) == (*expected, candle["volume"], identity.isin)
    row = connection.execute(
        "SELECT open,high,low,close FROM index_bars WHERE index_name=? AND trade_date=? AND available_at <= ?",
        (identity.name, candle["date"], verified_at),
    ).fetchone()
    return row is not None and tuple(row) == expected


def reconcile_provider(connection, reference_database, source_url, *, clock=None):
    """Atomically issue receipts only after every downloaded candle matches.

    A reference snapshot and retained-file hashes make the comparison reproducible.
    The operator asserts raw-source provenance; an HTTPS exchange URL alone cannot
    establish that the retained bytes were actually served by that exchange.
    """
    if not isinstance(source_url, str) or any(ord(c) < 33 for c in source_url):
        raise ValueError("Reference source URL must be a clean HTTPS exchange URL")
    try:
        url = urlsplit(source_url)
        valid_url = url.scheme == "https" and url.hostname in EXCHANGE_HOSTS and not any(
            (url.username, url.password, url.query, url.fragment)) and url.port in (None, 443)
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ValueError("Reference source URL must be HTTPS on an NSE exchange host without credentials or query parameters")
    has_downloads = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_downloads'"
    ).fetchone()
    if not has_downloads:
        raise ValueError("No provider download audit records are available to reconcile")
    downloads = connection.execute("SELECT * FROM provider_downloads ORDER BY sync_id, instrument_key").fetchall()
    if not downloads:
        raise ValueError("No provider downloads are available to reconcile")
    stamp = (clock or (lambda: datetime.now(timezone.utc)))()
    if stamp.tzinfo is None:
        raise ValueError("Reconciliation clock must be timezone-aware")
    verified_at = stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    receipts = []
    with tempfile.TemporaryDirectory(prefix="stockex-reference-") as temporary:
        snapshot = Path(temporary) / "reference.sqlite3"
        backup = backup_database(reference_database, snapshot)
        reference = sqlite3.connect(snapshot.as_uri() + "?mode=ro", uri=True)
        reference.row_factory = sqlite3.Row
        rebuilt = None
        try:
            rebuilt = open_market_db(Path(temporary) / "replayed.sqlite3")
            imports = _reference_imports(reference, reference_database)
            # Rebuild from the retained bytes; a manually edited reference DB
            # cannot establish that provider prices equal the raw source files.
            for record in imports:
                imported = import_market_file(rebuilt, record["path"], kind=record["kind"], available_at=verified_at)
                if imported["sha256"] != record["sha256"]:
                    raise ProviderError("REFERENCE_SOURCE_CHANGED", "Reference bytes changed between validation and replay")
            for download in downloads:
                if verified_at < download["retrieved_at"]:
                    raise ValueError("Reconciliation cannot precede provider retrieval")
                has_manifests = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_manifests'").fetchone()
                manifest_row = connection.execute("SELECT manifest_json FROM provider_manifests WHERE sha256=?",
                                                   (download["manifest_sha256"],)).fetchone() if has_manifests else None
                if manifest_row is None or hashlib.sha256(manifest_row[0].encode()).hexdigest() != download["manifest_sha256"]:
                    raise ProviderError("PROVIDER_MAPPING_UNAVAILABLE", "Reconciliation requires the retained, hash-matching instrument manifest; re-sync with the original mapping")
                identities = {item.instrument_key: item for item in validate_instruments(strict_json(manifest_row[0]))}
                identity = identities.get(download["instrument_key"])
                if identity is None or identity.name != download["name"]:
                    raise ProviderError("PROVIDER_MAPPING_CONFLICT", "Download audit and retained identity manifest disagree")
                raw_path = Path(download["raw_path"])
                with raw_path.open("rb") as handle:
                    raw = handle.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES or hashlib.sha256(raw).hexdigest() != download["raw_sha256"]:
                    raise ProviderError("PROVIDER_CACHE_CORRUPT", "Provider response no longer matches its audit hash")
                candles = parse_candles(raw, download["from_date"], download["to_date"])
                for candle in candles:
                    if not _matches(reference, identity, candle, verified_at) \
                            or not _matches(rebuilt, identity, candle, verified_at) \
                            or not _matches(connection, identity, candle, verified_at):
                        raise ProviderError("PROVIDER_RECONCILIATION_FAILED", "Provider history does not exactly match every supplied raw reference candle and identity")
                content = {"sync_id": download["sync_id"], "instrument_key": download["instrument_key"],
                           "raw_sha256": download["raw_sha256"], "reference_sha256": backup["sha256"],
                           "source_url": source_url, "matched_rows": len(candles), "reference_imports": imports}
                receipt_id = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                receipts.append({"receipt_id": receipt_id, **content})
        finally:
            if rebuilt is not None:
                rebuilt.close()
            reference.close()
        with atomic_transaction(connection):
            connection.execute("""CREATE TABLE IF NOT EXISTS provider_reconciliations (
                receipt_id TEXT PRIMARY KEY, sync_id TEXT NOT NULL, instrument_key TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL, reference_sha256 TEXT NOT NULL, source_url TEXT NOT NULL,
                verified_at TEXT NOT NULL, matched_rows INTEGER NOT NULL, reference_imports_json TEXT NOT NULL,
                price_basis TEXT NOT NULL)""")
            written = 0
            for receipt in receipts:
                cursor = connection.execute("INSERT OR IGNORE INTO provider_reconciliations VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (receipt["receipt_id"], receipt["sync_id"], receipt["instrument_key"], receipt["raw_sha256"],
                     receipt["reference_sha256"], source_url, verified_at, receipt["matched_rows"],
                     json.dumps(receipt["reference_imports"], sort_keys=True), "MATCHED_SUPPLIED_RAW"))
                written += cursor.rowcount
    return {"status": "MATCHED", "receipts": len(receipts), "new_receipts": written,
            "verified_at": verified_at, "reference_sha256": backup["sha256"],
            "price_basis": "MATCHED_SUPPLIED_RAW", "source_url": source_url,
            "assurance": "Exact agreement with retained supplied raw files for matched dates only; source authenticity and other dates are not certified."}
