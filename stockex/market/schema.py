"""SQLite tables for imported NSE end-of-day market files.

These tables are versioned separately from the evidence store. Use separate
database files: their corporate_actions tables have different contracts.
"""

import sqlite3
from ..operations import atomic_transaction


MARKET_SCHEMA_VERSION = 5

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS market_import_runs (
        run_id TEXT PRIMARY KEY,
        sha256 TEXT NOT NULL,
        kind TEXT NOT NULL,
        options_json TEXT NOT NULL,
        rows INTEGER NOT NULL,
        skipped_json TEXT NOT NULL,
        imported_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_imports (
        sha256 TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        path TEXT NOT NULL,
        rows INTEGER NOT NULL,
        imported_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bars (
        symbol TEXT NOT NULL,
        series TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        prev_close REAL,
        volume INTEGER NOT NULL,
        traded_value REAL,
        trades INTEGER,
        delivery_qty INTEGER,
        delivery_pct REAL,
        isin TEXT,
        available_at TEXT NOT NULL,
        PRIMARY KEY (symbol, series, trade_date),
        CHECK (high >= low AND volume >= 0)
    )
    """,
    "CREATE INDEX IF NOT EXISTS bars_by_date ON bars (trade_date)",
    """
    CREATE TABLE IF NOT EXISTS index_bars (
        index_name TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL NOT NULL,
        available_at TEXT NOT NULL,
        PRIMARY KEY (index_name, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fo_bars (
        symbol TEXT NOT NULL,
        instrument TEXT NOT NULL CHECK (instrument IN ('FUT', 'CE', 'PE')),
        expiry TEXT NOT NULL,
        strike REAL NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        settle REAL,
        underlying REAL,
        open_interest INTEGER,
        oi_change INTEGER,
        volume INTEGER,
        is_index INTEGER NOT NULL DEFAULT 0,
        available_at TEXT NOT NULL,
        PRIMARY KEY (symbol, instrument, expiry, strike, trade_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS fo_by_symbol_date ON fo_bars (symbol, trade_date)",
    """
    CREATE TABLE IF NOT EXISTS deals (
        kind TEXT NOT NULL CHECK (kind IN ('BULK', 'BLOCK')),
        deal_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        client TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        available_at TEXT NOT NULL,
        PRIMARY KEY (kind, deal_date, symbol, client, side, quantity, price)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS corporate_actions (
        symbol TEXT NOT NULL,
        ex_date TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('SPLIT', 'BONUS', 'CONSOLIDATION')),
        factor REAL NOT NULL CHECK (factor > 0),
        purpose TEXT,
        available_at TEXT NOT NULL,
        PRIMARY KEY (symbol, ex_date, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_members (
        index_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        industry TEXT,
        isin TEXT,
        as_of_date TEXT NOT NULL,
        PRIMARY KEY (index_name, symbol, as_of_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS announcements (
        symbol TEXT NOT NULL,
        broadcast_at TEXT NOT NULL,
        subject TEXT NOT NULL,
        details TEXT,
        category TEXT,
        category_source TEXT,
        PRIMARY KEY (symbol, broadcast_at, subject)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS announcement_classifications (
        classification_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        broadcast_at TEXT NOT NULL,
        subject TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        question_bank_version TEXT NOT NULL,
        model_requested TEXT NOT NULL,
        model_returned TEXT NOT NULL,
        judged_at TEXT NOT NULL,
        confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
        confidence_floor REAL NOT NULL CHECK(confidence_floor > 0 AND confidence_floor <= 1),
        category TEXT NOT NULL,
        applied_category TEXT NOT NULL,
        response_json TEXT NOT NULL,
        UNIQUE(symbol, broadcast_at, subject, input_sha256, question_bank_version, model_requested, confidence_floor),
        FOREIGN KEY(symbol, broadcast_at, subject) REFERENCES announcements(symbol, broadcast_at, subject)
    )
    """,
    "CREATE INDEX IF NOT EXISTS announcement_classifications_cutoff ON announcement_classifications(judged_at)",
    """CREATE TRIGGER IF NOT EXISTS immutable_announcement_classification_update
       BEFORE UPDATE ON announcement_classifications BEGIN
       SELECT RAISE(ABORT, 'Announcement classifications are immutable'); END""",
    """CREATE TRIGGER IF NOT EXISTS immutable_announcement_classification_delete
       BEFORE DELETE ON announcement_classifications BEGIN
       SELECT RAISE(ABORT, 'Announcement classifications are immutable'); END""",
    """
    CREATE TABLE IF NOT EXISTS journal (
        scan_date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        setup TEXT NOT NULL,
        setup_version INTEGER NOT NULL,
        rank INTEGER,
        plan_json TEXT NOT NULL,
        judge_json TEXT,
        regime TEXT,
        recorded_at TEXT NOT NULL,
        outcome_json TEXT,
        PRIMARY KEY (scan_date, symbol, setup)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS restrictions (
        list_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        stage TEXT,
        from_date TEXT NOT NULL,
        to_date TEXT,
        available_at TEXT NOT NULL,
        PRIMARY KEY (list_name, symbol, from_date)
    )
    """,
)


def initialize_market_schema(connection: sqlite3.Connection) -> None:
    with atomic_transaction(connection):
        _initialize_market_schema(connection)


def _initialize_market_schema(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_schema_version'"
    ).fetchone()
    if existing:
        version = connection.execute("SELECT MAX(version) FROM market_schema_version").fetchone()[0]
        if version is not None and version > MARKET_SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"Market schema version {version} is newer than this code ({MARKET_SCHEMA_VERSION})"
            )
    # The evidence store uses a different corporate_actions contract.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(corporate_actions)")}
    if columns and "symbol" not in columns:
        raise sqlite3.DatabaseError("Use separate database files for market data and the evidence store")
    for statement in _TABLES:
        connection.execute(statement)
    # Old rows have no historical publication evidence. Make them visible only
    # from migration time, rather than manufacturing knowledge at their ex-date.
    for table in ("corporate_actions", "restrictions"):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if "available_at" not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN available_at TEXT")
            connection.execute(
                f"UPDATE {table} SET available_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
            )
    row = connection.execute("SELECT MAX(version) FROM market_schema_version").fetchone()
    if row[0] is None or row[0] < MARKET_SCHEMA_VERSION:
        # New tables are created above with IF NOT EXISTS, so upgrading only records the version.
        connection.execute(
            "INSERT INTO market_schema_version (version, applied_at) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (MARKET_SCHEMA_VERSION,),
        )
    elif row[0] > MARKET_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"Market schema version {row[0]} is newer than this code ({MARKET_SCHEMA_VERSION})"
        )


def open_market_db(path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        initialize_market_schema(connection)
    except BaseException:
        connection.close()
        raise
    return connection
