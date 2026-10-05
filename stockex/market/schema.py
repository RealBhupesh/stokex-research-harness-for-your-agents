"""SQLite tables for imported NSE end-of-day market files.

These tables are versioned separately from the evidence store so either can
evolve without migrating the other. Both may live in the same database file.
"""

import sqlite3


MARKET_SCHEMA_VERSION = 1

_TABLES = (
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
    CREATE TABLE IF NOT EXISTS restrictions (
        list_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        stage TEXT,
        from_date TEXT NOT NULL,
        to_date TEXT,
        PRIMARY KEY (list_name, symbol, from_date)
    )
    """,
)


def initialize_market_schema(connection: sqlite3.Connection) -> None:
    for statement in _TABLES:
        connection.execute(statement)
    row = connection.execute("SELECT MAX(version) FROM market_schema_version").fetchone()
    if row[0] is None:
        connection.execute(
            "INSERT INTO market_schema_version (version, applied_at) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (MARKET_SCHEMA_VERSION,),
        )
    elif row[0] > MARKET_SCHEMA_VERSION:
        raise sqlite3.DatabaseError(
            f"Market schema version {row[0]} is newer than this code ({MARKET_SCHEMA_VERSION})"
        )
    connection.commit()


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
