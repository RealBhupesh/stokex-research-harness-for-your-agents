"""Versioned SQLite schema for the point-in-time evidence store."""

import sqlite3


SCHEMA_VERSION = 2

_UTC_TIMESTAMP = (
    "{column} IS NULL OR "
    "(strftime('%Y-%m-%dT%H:%M:%SZ', {column}) IS NOT NULL "
    "AND strftime('%Y-%m-%dT%H:%M:%SZ', {column}) = {column})"
)

_TIMESTAMP_COLUMNS = {
    "schema_migrations": ("applied_at",),
    "sources": ("published_at", "available_at", "retrieved_at"),
    "security_symbols": ("valid_from", "valid_to"),
    "observations": ("period_start", "period_end", "available_at", "valid_from", "valid_to"),
    "universe_memberships": ("effective_from", "effective_to"),
    "corporate_actions": ("available_at", "ex_date", "record_date", "effective_date"),
}


def _validate_timestamps(connection: sqlite3.Connection) -> None:
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            expression = _UTC_TIMESTAMP.format(column=column)
            row = connection.execute(
                f"SELECT 1 FROM {table} WHERE {column} IS NOT NULL AND NOT ({expression}) LIMIT 1"
            ).fetchone()
            if row is not None:
                raise sqlite3.IntegrityError(
                    f"legacy {table}.{column} contains a non-canonical UTC timestamp"
                )


def _normalize_legacy_migration_timestamps(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    for version, applied_at in rows:
        if applied_at is None:
            raise sqlite3.IntegrityError("schema_migrations.applied_at cannot be null")
        normalized = connection.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%SZ', ?)", (applied_at,)
        ).fetchone()[0]
        if normalized is None:
            raise sqlite3.IntegrityError(
                "legacy schema_migrations.applied_at is not a valid timestamp"
            )
        connection.execute(
            "UPDATE schema_migrations SET applied_at = ? WHERE version = ?",
            (normalized, version),
        )


def _install_timestamp_triggers(connection: sqlite3.Connection) -> None:
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            condition = _UTC_TIMESTAMP.format(column=f"NEW.{column}")
            trigger_name = f"{table}_{column}_utc_timestamp"
            connection.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_name}
                BEFORE INSERT ON {table}
                WHEN NOT ({condition})
                BEGIN
                    SELECT RAISE(ABORT, 'timestamp must be canonical UTC ISO 8601');
                END
                """
            )
            connection.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS {trigger_name}_update
                BEFORE UPDATE OF {column} ON {table}
                WHEN NOT ({condition})
                BEGIN
                    SELECT RAISE(ABORT, 'timestamp must be canonical UTC ISO 8601');
                END
                """
            )


def current_schema_version(connection: sqlite3.Connection) -> int:
    """Return the highest applied migration version, or zero for a new database."""
    table_exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if table_exists is None:
        return 0
    row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0])


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create the version-one evidence schema in one idempotent transaction."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    existing_version = current_schema_version(connection)

    with connection:
        connection.execute("BEGIN")
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                CHECK ({_UTC_TIMESTAMP.format(column='applied_at')})
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS issuers (
                issuer_id TEXT PRIMARY KEY NOT NULL,
                legal_name TEXT,
                cin TEXT,
                lei TEXT,
                status TEXT CHECK (status IN ('ACTIVE', 'MERGED', 'DELISTED', 'DISSOLVED', 'UNKNOWN')),
                metadata_json TEXT,
                canonical_json TEXT
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY NOT NULL,
                publisher TEXT,
                source_class TEXT,
                uri TEXT,
                published_at TEXT,
                available_at TEXT,
                retrieved_at TEXT,
                content_hash TEXT,
                metadata_json TEXT,
                canonical_json TEXT,
                CHECK ({_UTC_TIMESTAMP.format(column='published_at')}),
                CHECK ({_UTC_TIMESTAMP.format(column='available_at')}),
                CHECK ({_UTC_TIMESTAMP.format(column='retrieved_at')})
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS securities (
                security_id TEXT PRIMARY KEY NOT NULL,
                issuer_id TEXT NOT NULL REFERENCES issuers(issuer_id),
                isin TEXT UNIQUE,
                exchange TEXT CHECK (exchange IN ('NSE', 'BSE')),
                instrument_type TEXT,
                canonical_json TEXT
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS security_symbols (
                symbol_id TEXT PRIMARY KEY NOT NULL,
                security_id TEXT NOT NULL REFERENCES securities(security_id),
                symbol TEXT,
                valid_from TEXT,
                valid_to TEXT,
                source_id TEXT REFERENCES sources(source_id),
                canonical_json TEXT,
                CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from),
                CHECK ({_UTC_TIMESTAMP.format(column='valid_from')}),
                CHECK ({_UTC_TIMESTAMP.format(column='valid_to')})
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY NOT NULL,
                security_id TEXT NOT NULL REFERENCES securities(security_id),
                field TEXT,
                value_type TEXT CHECK (value_type IN ('NUMBER', 'TEXT', 'BOOLEAN', 'DATE', 'JSON')),
                value_number REAL,
                value_text TEXT,
                unit TEXT,
                period_start TEXT,
                period_end TEXT,
                source_id TEXT REFERENCES sources(source_id),
                available_at TEXT,
                valid_from TEXT,
                valid_to TEXT,
                revision_of TEXT REFERENCES observations(observation_id),
                revision_number INTEGER CHECK (revision_number IS NULL OR revision_number >= 0),
                quality_status TEXT CHECK (quality_status IN ('VERIFIED', 'PROVISIONAL', 'ASSUMED_LAG', 'QUARANTINED')),
                metadata_json TEXT,
                canonical_json TEXT,
                CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start),
                CHECK ({_UTC_TIMESTAMP.format(column='period_start')}),
                CHECK ({_UTC_TIMESTAMP.format(column='period_end')}),
                CHECK ({_UTC_TIMESTAMP.format(column='available_at')}),
                CHECK ({_UTC_TIMESTAMP.format(column='valid_from')}),
                CHECK ({_UTC_TIMESTAMP.format(column='valid_to')}),
                CHECK ((value_number IS NOT NULL) + (value_text IS NOT NULL) = 1)
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS universe_memberships (
                membership_id TEXT PRIMARY KEY NOT NULL,
                universe_id TEXT,
                security_id TEXT NOT NULL REFERENCES securities(security_id),
                effective_from TEXT,
                effective_to TEXT,
                source_id TEXT REFERENCES sources(source_id),
                metadata_json TEXT,
                canonical_json TEXT,
                CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from),
                CHECK ({_UTC_TIMESTAMP.format(column='effective_from')}),
                CHECK ({_UTC_TIMESTAMP.format(column='effective_to')})
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS corporate_actions (
                action_id TEXT PRIMARY KEY NOT NULL,
                security_id TEXT NOT NULL REFERENCES securities(security_id),
                action_type TEXT,
                source_id TEXT REFERENCES sources(source_id),
                available_at TEXT,
                ex_date TEXT,
                record_date TEXT,
                effective_date TEXT,
                ratio REAL,
                cash_amount REAL,
                currency TEXT,
                status TEXT,
                metadata_json TEXT,
                canonical_json TEXT,
                CHECK ({_UTC_TIMESTAMP.format(column='available_at')}),
                CHECK ({_UTC_TIMESTAMP.format(column='ex_date')}),
                CHECK ({_UTC_TIMESTAMP.format(column='record_date')}),
                CHECK ({_UTC_TIMESTAMP.format(column='effective_date')})
            )
            """
        )
        if existing_version == 1:
            _normalize_legacy_migration_timestamps(connection)
            _validate_timestamps(connection)
        _install_timestamp_triggers(connection)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (SCHEMA_VERSION,),
        )
        protected_columns = (
            "observation_id", "security_id", "field", "value_type", "value_number",
            "value_text", "unit", "period_start", "period_end", "source_id",
            "available_at", "valid_from", "revision_of", "revision_number",
            "quality_status", "metadata_json", "canonical_json",
        )
        for column in protected_columns:
            connection.execute(
                f"""
                CREATE TRIGGER IF NOT EXISTS observations_no_update_{column}
                BEFORE UPDATE OF {column} ON observations
                BEGIN
                    SELECT RAISE(ABORT, 'observations are append-only');
                END
                """
            )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS observations_no_delete
            BEFORE DELETE ON observations
            BEGIN
                SELECT RAISE(ABORT, 'observations are append-only');
            END
            """
        )
        connection.execute(
            """
            CREATE TRIGGER IF NOT EXISTS observations_valid_to_once
            BEFORE UPDATE OF valid_to ON observations
            WHEN OLD.valid_to IS NOT NULL OR NEW.valid_to IS NULL
            BEGIN
                SELECT RAISE(ABORT, 'observation valid_to can only be closed once');
            END
            """
        )
