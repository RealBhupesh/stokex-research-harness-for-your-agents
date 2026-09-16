"""SQLite persistence for point-in-time identity and source records."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Callable, Iterator

from .records import (
    IssuerRecord,
    ObservationRecord,
    Record,
    CorporateActionRecord,
    SecurityRecord,
    SecuritySymbolRecord,
    SourceRecord,
    StoreValidationError,
    UniverseMembershipRecord,
    canonical_json,
    normalize_timestamp,
)
from .schema import SCHEMA_VERSION, current_schema_version, initialize_database


_SQLITE_HEADER = b"SQLite format 3\x00"

_INTEGRITY_TIMESTAMP_COLUMNS = (
    ("schema_migrations", "version", ("applied_at",)),
    ("sources", "source_id", ("published_at", "available_at", "retrieved_at")),
    ("security_symbols", "symbol_id", ("valid_from", "valid_to")),
    (
        "observations", "observation_id",
        ("period_start", "period_end", "available_at", "valid_from", "valid_to"),
    ),
    ("universe_memberships", "membership_id", ("effective_from", "effective_to")),
    (
        "corporate_actions", "action_id",
        ("available_at", "ex_date", "record_date", "effective_date"),
    ),
)


@dataclass(frozen=True)
class IngestResult:
    record_type: str
    record_id: str
    status: str


@dataclass(frozen=True)
class _RecordMapping:
    record_type: str
    table: str
    id_column: str
    columns: tuple[str, ...]


_MAPPINGS = {
    IssuerRecord: _RecordMapping(
        "issuer",
        "issuers",
        "issuer_id",
        ("issuer_id", "legal_name", "cin", "lei", "status", "metadata_json", "canonical_json"),
    ),
    SecurityRecord: _RecordMapping(
        "security",
        "securities",
        "security_id",
        ("security_id", "issuer_id", "isin", "exchange", "instrument_type", "canonical_json"),
    ),
    SecuritySymbolRecord: _RecordMapping(
        "security_symbol",
        "security_symbols",
        "symbol_id",
        ("symbol_id", "security_id", "symbol", "valid_from", "valid_to", "source_id", "canonical_json"),
    ),
    SourceRecord: _RecordMapping(
        "source",
        "sources",
        "source_id",
        (
            "source_id",
            "publisher",
            "source_class",
            "uri",
            "published_at",
            "available_at",
            "retrieved_at",
            "content_hash",
            "metadata_json",
            "canonical_json",
        ),
    ),
    ObservationRecord: _RecordMapping(
        "observation",
        "observations",
        "observation_id",
        (
            "observation_id",
            "security_id",
            "field",
            "value_type",
            "value_number",
            "value_text",
            "unit",
            "period_start",
            "period_end",
            "source_id",
            "available_at",
            "valid_from",
            "valid_to",
            "revision_of",
            "revision_number",
            "quality_status",
            "metadata_json",
            "canonical_json",
        ),
    ),
    UniverseMembershipRecord: _RecordMapping(
        "universe_membership",
        "universe_memberships",
        "membership_id",
        (
            "membership_id", "universe_id", "security_id", "effective_from", "effective_to",
            "source_id", "metadata_json", "canonical_json",
        ),
    ),
    CorporateActionRecord: _RecordMapping(
        "corporate_action",
        "corporate_actions",
        "action_id",
        (
            "action_id", "security_id", "action_type", "source_id", "available_at", "ex_date",
            "record_date", "effective_date", "ratio", "cash_amount", "currency", "status",
            "metadata_json", "canonical_json",
        ),
    ),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class PointInTimeStore:
    """Own a SQLite connection and persist validated identity evidence."""

    def __init__(self, connection: sqlite3.Connection, clock: Callable[[], datetime]):
        self.connection = connection
        self._clock = clock
        self._closed = False
        self._transaction_active = False

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> "PointInTimeStore":
        database_path = Path(path)
        if database_path.exists():
            if not database_path.is_file() or _read_header(database_path) != _SQLITE_HEADER:
                raise ValueError(f"Existing database is not a SQLite file: {database_path}")
        elif not database_path.parent.is_dir():
            raise FileNotFoundError(f"Database parent directory does not exist: {database_path.parent}")

        connection = sqlite3.connect(str(database_path))
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            initialize_database(connection)
        except BaseException:
            connection.close()
            raise
        return cls(connection, clock or _utc_now)

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self) -> "PointInTimeStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator["PointInTimeStore"]:
        self._ensure_open()
        if self.connection.in_transaction:
            raise sqlite3.ProgrammingError("A transaction is already active")
        try:
            self.connection.execute("BEGIN")
            self._transaction_active = True
            yield self
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        finally:
            self._transaction_active = False

    def ingest(self, record: Record, *, commit: bool = True) -> IngestResult:
        """Persist one validated record, rejecting non-idempotent ID reuse."""
        self._ensure_open()
        mapping = _MAPPINGS.get(type(record))
        if mapping is None:
            raise StoreValidationError(
                "RECORD_TYPE_UNSUPPORTED",
                "record",
                "This store cannot yet persist this record type",
            )

        record_id = getattr(record, mapping.id_column)
        try:
            if isinstance(record, ObservationRecord) and record.valid_to is not None:
                raise StoreValidationError(
                    "OBSERVATION_VALID_TO_MANAGED",
                    "record.valid_to",
                    "Observation valid_to is maintained only when a revision closes its parent",
                )
            existing = self.connection.execute(
                f"SELECT canonical_json FROM {mapping.table} WHERE {mapping.id_column} = ?",
                (record_id,),
            ).fetchone()
            if existing is not None:
                if existing["canonical_json"] == record.canonical_json:
                    result = IngestResult(mapping.record_type, record_id, "UNCHANGED")
                else:
                    raise StoreValidationError(
                        "IDEMPOTENCY_CONFLICT",
                        f"record.{mapping.id_column}",
                        "An existing record ID has different canonical content",
                    )
            else:
                self._assert_dependencies(record)
                if isinstance(record, SecuritySymbolRecord):
                    self._assert_symbol_interval_available(record)
                if isinstance(record, UniverseMembershipRecord):
                    self._assert_membership_interval_available(record)
                if isinstance(record, ObservationRecord):
                    parent = self._assert_observation_revision(record)
                values = _storage_values(record, mapping)
                placeholders = ", ".join("?" for _ in mapping.columns)
                self.connection.execute(
                    f"INSERT INTO {mapping.table} ({', '.join(mapping.columns)}) VALUES ({placeholders})",
                    values,
                )
                if isinstance(record, ObservationRecord) and parent is not None:
                    self.connection.execute(
                        "UPDATE observations SET valid_to = ? WHERE observation_id = ?",
                        (record.valid_from, parent["observation_id"]),
                    )
                result = IngestResult(mapping.record_type, record_id, "INSERTED")
            if commit and not self._transaction_active:
                self.connection.commit()
            return result
        except sqlite3.IntegrityError as error:
            if commit and not self._transaction_active:
                self.connection.rollback()
            self._raise_foreign_key_error(record, error)
            raise
        except BaseException:
            if commit and not self._transaction_active:
                self.connection.rollback()
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed PointInTimeStore")

    def _assert_dependencies(self, record: Record) -> None:
        if isinstance(record, SecurityRecord):
            self._assert_exists("issuers", "issuer_id", record.issuer_id, "ISSUER_MISSING", "record.issuer_id")
        elif isinstance(record, SecuritySymbolRecord):
            self._assert_exists(
                "securities", "security_id", record.security_id, "SECURITY_MISSING", "record.security_id"
            )
            if record.source_id is not None:
                self._assert_exists(
                    "sources", "source_id", record.source_id, "SOURCE_MISSING", "record.source_id"
                )
        elif isinstance(record, ObservationRecord):
            self._assert_exists(
                "securities", "security_id", record.security_id, "SECURITY_MISSING", "record.security_id"
            )
            self._assert_exists("sources", "source_id", record.source_id, "SOURCE_MISSING", "record.source_id")
        elif isinstance(record, (UniverseMembershipRecord, CorporateActionRecord)):
            self._assert_exists(
                "securities", "security_id", record.security_id, "SECURITY_MISSING", "record.security_id"
            )
            if record.source_id is not None:
                self._assert_exists(
                    "sources", "source_id", record.source_id, "SOURCE_MISSING", "record.source_id"
                )

    def _assert_observation_revision(self, record: ObservationRecord) -> sqlite3.Row | None:
        if record.revision_of is None:
            if record.revision_number != 0:
                raise StoreValidationError(
                    "REVISION_ORIGINAL_INVALID",
                    "record.revision_number",
                    "Original observations must have revision number zero",
                )
            return None

        parent = self.connection.execute(
            """
            SELECT observation_id, security_id, field, available_at, valid_from, valid_to, revision_number
            FROM observations
            WHERE observation_id = ?
            """,
            (record.revision_of,),
        ).fetchone()
        if parent is None:
            raise StoreValidationError(
                "REVISION_PARENT_MISSING",
                "record.revision_of",
                "Revision parent observation does not exist",
            )
        if record.security_id != parent["security_id"]:
            raise StoreValidationError(
                "REVISION_SECURITY_MISMATCH",
                "record.security_id",
                "Revision security must match its parent",
            )
        if record.field != parent["field"]:
            raise StoreValidationError(
                "REVISION_FIELD_MISMATCH",
                "record.field",
                "Revision field must match its parent",
            )
        if record.revision_number != parent["revision_number"] + 1:
            raise StoreValidationError(
                "REVISION_NUMBER_INVALID",
                "record.revision_number",
                "Revision number must immediately follow its parent",
            )
        if record.available_at < parent["available_at"]:
            raise StoreValidationError(
                "REVISION_AVAILABLE_AT_INVALID",
                "record.available_at",
                "Revision availability cannot precede its parent",
            )
        if record.valid_from is None:
            raise StoreValidationError(
                "REVISION_VALID_FROM_INVALID",
                "record.valid_from",
                "Revision validity start is required to close its parent",
            )
        if parent["valid_from"] is not None and record.valid_from < parent["valid_from"]:
            raise StoreValidationError(
                "REVISION_INTERVAL_INVALID",
                "record.valid_from",
                "Revision validity start would create a negative parent interval",
            )
        source = self.connection.execute(
            "SELECT available_at FROM sources WHERE source_id = ?", (record.source_id,)
        ).fetchone()
        if (
            record.valid_from < record.available_at
            or source is None
            or source["available_at"] is None
            or record.valid_from < source["available_at"]
        ):
            raise StoreValidationError(
                "REVISION_VALID_FROM_INVALID",
                "record.valid_from",
                "Revision validity cannot precede its own or its source's known availability",
            )
        if parent["valid_to"] is not None:
            raise StoreValidationError(
                "REVISION_PARENT_CLOSED",
                "record.revision_of",
                "Revision parent validity interval is already closed",
            )
        return parent

    def observation_as_of(self, security_id: str, field: str, cutoff: str) -> dict | None:
        """Return the latest eligible observation and its source at ``cutoff``."""
        self._ensure_open()
        normalized_cutoff = normalize_timestamp(cutoff, "cutoff")
        row = self.connection.execute(
            """
            SELECT
                o.observation_id,
                o.security_id,
                o.field,
                o.value_type,
                o.value_number,
                o.value_text,
                o.unit,
                o.period_start,
                o.period_end,
                o.source_id,
                o.available_at,
                o.valid_from,
                o.valid_to,
                o.revision_of,
                o.revision_number,
                o.quality_status,
                o.metadata_json,
                o.canonical_json,
                s.publisher AS source_publisher,
                s.source_class AS source_source_class,
                s.uri AS source_uri,
                s.published_at AS source_published_at,
                s.available_at AS source_available_at,
                s.retrieved_at AS source_retrieved_at,
                s.content_hash AS source_content_hash,
                s.metadata_json AS source_metadata_json,
                s.canonical_json AS source_canonical_json
            FROM observations AS o
            JOIN sources AS s ON s.source_id = o.source_id
            WHERE o.security_id = ? AND o.field = ?
              AND o.available_at <= ? AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR ? < o.valid_to)
              AND o.quality_status != 'QUARANTINED'
              AND s.available_at IS NOT NULL AND s.available_at <= ?
            ORDER BY o.valid_from DESC, o.revision_number DESC, o.observation_id ASC
            LIMIT 1
            """,
            (
                security_id, field, normalized_cutoff, normalized_cutoff,
                normalized_cutoff, normalized_cutoff,
            ),
        ).fetchone()
        if row is None:
            return None

        observation = {
            key: row[key]
            for key in (
                "observation_id", "security_id", "field", "value_type", "value_number",
                "value_text", "unit", "period_start", "period_end", "source_id",
                "available_at", "valid_from", "valid_to", "revision_of", "revision_number",
                "quality_status", "metadata_json", "canonical_json",
            )
        }
        observation["source"] = {
            "source_id": row["source_id"],
            "publisher": row["source_publisher"],
            "source_class": row["source_source_class"],
            "uri": row["source_uri"],
            "published_at": row["source_published_at"],
            "available_at": row["source_available_at"],
            "retrieved_at": row["source_retrieved_at"],
            "content_hash": row["source_content_hash"],
            "metadata_json": row["source_metadata_json"],
            "canonical_json": row["source_canonical_json"],
        }
        observation["value"] = _query_value(observation)
        return observation

    def universe_as_of(self, universe_id: str, cutoff: str) -> list[dict]:
        """Reconstruct the securities (and their symbols) in a universe at ``cutoff``."""
        self._ensure_open()
        normalized_cutoff = normalize_timestamp(cutoff, "cutoff")
        rows = self.connection.execute(
            """
            SELECT
                m.membership_id, m.universe_id, m.effective_from, m.effective_to,
                m.metadata_json AS membership_metadata_json, m.canonical_json AS membership_canonical_json,
                sec.security_id, sec.issuer_id, sec.isin, sec.exchange, sec.instrument_type,
                sym.symbol_id, sym.symbol, sym.valid_from AS symbol_valid_from,
                sym.valid_to AS symbol_valid_to, sym.source_id AS symbol_source_id
            FROM universe_memberships AS m
            JOIN securities AS sec ON sec.security_id = m.security_id
            JOIN security_symbols AS sym ON sym.security_id = sec.security_id
                AND (sym.valid_from IS NULL OR sym.valid_from <= ?)
                AND (sym.valid_to IS NULL OR ? < sym.valid_to)
            LEFT JOIN sources AS membership_source ON membership_source.source_id = m.source_id
            LEFT JOIN sources AS symbol_source ON symbol_source.source_id = sym.source_id
            WHERE m.universe_id = ?
                AND (m.effective_from IS NULL OR m.effective_from <= ?)
                AND (m.effective_to IS NULL OR ? < m.effective_to)
                AND (m.source_id IS NULL OR (
                    membership_source.available_at IS NOT NULL AND membership_source.available_at <= ?
                ))
                AND (sym.source_id IS NULL OR (
                    symbol_source.available_at IS NOT NULL AND symbol_source.available_at <= ?
                ))
            ORDER BY sec.security_id ASC, sym.symbol_id ASC, m.membership_id ASC
            """,
            (
                normalized_cutoff, normalized_cutoff, universe_id, normalized_cutoff,
                normalized_cutoff, normalized_cutoff, normalized_cutoff,
            ),
        ).fetchall()
        return [
            {
                "membership_id": row["membership_id"],
                "universe_id": row["universe_id"],
                "effective_from": row["effective_from"],
                "effective_to": row["effective_to"],
                "metadata_json": row["membership_metadata_json"],
                "canonical_json": row["membership_canonical_json"],
                "security_id": row["security_id"],
                "issuer_id": row["issuer_id"],
                "isin": row["isin"],
                "exchange": row["exchange"],
                "instrument_type": row["instrument_type"],
                "symbol_id": row["symbol_id"],
                "symbol": row["symbol"],
                "symbol_valid_from": row["symbol_valid_from"],
                "symbol_valid_to": row["symbol_valid_to"],
                "symbol_source_id": row["symbol_source_id"],
            }
            for row in rows
        ]

    def evidence_packet(
        self,
        security_id: str,
        cutoff: str,
        fields: list[str] | None = None,
    ) -> dict:
        """Return deterministic, cutoff-valid evidence for one security."""
        self._ensure_open()
        normalized_cutoff = normalize_timestamp(cutoff, "cutoff")
        requested_fields = _normalize_fields(fields)
        if requested_fields is None:
            requested_fields = [
                row["field"] for row in self.connection.execute(
                    "SELECT DISTINCT field FROM observations WHERE security_id = ? ORDER BY field ASC",
                    (security_id,),
                )
            ]

        observations = self._observations_for_fields(security_id, normalized_cutoff, requested_fields)
        selected_fields = {row["field"] for row in observations}
        gaps = [field for field in requested_fields if field not in selected_fields]
        conflicts = self._observation_conflicts(security_id, normalized_cutoff, requested_fields)
        corporate_actions = self._corporate_actions_as_of(security_id, normalized_cutoff)
        source_ids = {
            row["source_id"] for row in observations + corporate_actions if row["source_id"] is not None
        }
        source_ids.update(
            observation["source_id"]
            for conflict in conflicts
            for observation in conflict["observations"]
            if observation["source_id"] is not None
        )
        excluded_quarantined_count = self._quarantined_count(
            security_id, normalized_cutoff, requested_fields
        )
        return {
            "schema_version": 1,
            "security_id": security_id,
            "cutoff": normalized_cutoff,
            "generated_at": _clock_timestamp(self._clock),
            "observations": observations,
            "corporate_actions": corporate_actions,
            "sources": self._sources_by_id(source_ids, normalized_cutoff),
            "conflicts": conflicts,
            "gaps": gaps,
            "integrity": {
                "strict_point_in_time": True,
                "quarantined_records_excluded": excluded_quarantined_count,
            },
        }

    def integrity_report(self) -> dict:
        """Diagnose corruption that cannot be represented by normal ingestion."""
        self._ensure_open()
        errors: list[dict] = []
        warnings: list[dict] = []

        stored_schema_version = current_schema_version(self.connection)
        if stored_schema_version != SCHEMA_VERSION:
            errors.append({
                "code": "SCHEMA_VERSION_INVALID",
                "expected": SCHEMA_VERSION,
                "actual": stored_schema_version,
            })

        for table, identifier, columns in _INTEGRITY_TIMESTAMP_COLUMNS:
            for column in columns:
                rows = self.connection.execute(
                    f"""
                    SELECT {identifier} AS record_id
                    FROM {table}
                    WHERE {column} IS NOT NULL
                      AND (
                        strftime('%Y-%m-%dT%H:%M:%SZ', {column}) IS NULL
                        OR strftime('%Y-%m-%dT%H:%M:%SZ', {column}) != {column}
                      )
                    ORDER BY {identifier} ASC
                    """
                ).fetchall()
                errors.extend({
                    "code": "TIMESTAMP_INVALID",
                    "table": table,
                    "record_id": row["record_id"],
                    "column": column,
                } for row in rows)

        for row in self.connection.execute("PRAGMA foreign_key_check"):
            errors.append({
                "code": "FOREIGN_KEY_VIOLATION",
                "table": row["table"],
                "rowid": row["rowid"],
                "parent": row["parent"],
                "foreign_key": row["fkid"],
            })

        for table, identifier, start, end in (
            ("security_symbols", "symbol_id", "valid_from", "valid_to"),
            ("universe_memberships", "membership_id", "effective_from", "effective_to"),
            ("observations", "observation_id", "valid_from", "valid_to"),
            ("observations", "observation_id", "period_start", "period_end"),
        ):
            rows = self.connection.execute(
                f"""
                SELECT {identifier} AS record_id FROM {table}
                WHERE {start} IS NOT NULL AND {end} IS NOT NULL AND {end} <= {start}
                ORDER BY {identifier} ASC
                """
            ).fetchall()
            errors.extend({
                "code": "INVALID_INTERVAL", "table": table, "record_id": row["record_id"],
                "start": start, "end": end,
            } for row in rows)

        revision_rows = self.connection.execute(
            """
            SELECT child.observation_id
            FROM observations AS child
            LEFT JOIN observations AS parent ON parent.observation_id = child.revision_of
            LEFT JOIN sources AS source ON source.source_id = child.source_id
            WHERE (child.revision_of IS NULL AND (child.revision_number IS NULL OR child.revision_number != 0))
               OR (child.revision_of IS NOT NULL AND (
                    parent.observation_id IS NULL
                    OR child.security_id != parent.security_id
                    OR child.field != parent.field
                    OR child.revision_number IS NULL
                    OR parent.revision_number IS NULL
                    OR child.revision_number != parent.revision_number + 1
                    OR child.available_at IS NULL
                    OR child.available_at < parent.available_at
                    OR child.valid_from IS NULL
                    OR child.valid_from < parent.valid_from
                    OR child.valid_from < child.available_at
                    OR source.available_at IS NULL
                    OR child.valid_from < source.available_at
                    OR parent.valid_to IS NULL
                    OR parent.valid_to != child.valid_from
                ))
            ORDER BY child.observation_id ASC
            """
        ).fetchall()
        errors.extend({"code": "REVISION_CHAIN_INVALID", "observation_id": row["observation_id"]}
                      for row in revision_rows)

        errors.extend(self._overlap_problems(
            "security_symbols", "symbol_id", ("security_id",), "valid_from", "valid_to", "SYMBOL_INTERVAL_OVERLAP"
        ))
        errors.extend(self._overlap_problems(
            "universe_memberships", "membership_id", ("universe_id", "security_id"),
            "effective_from", "effective_to", "MEMBERSHIP_OVERLAP",
        ))

        for conflict in self._active_observation_conflicts():
            problem = {
                "code": "EQUAL_TIME_CONFLICT",
                "security_id": conflict["security_id"],
                "field": conflict["field"],
                "valid_from": conflict["valid_from"],
                "available_at": conflict["available_at"],
                "observation_ids": conflict["observation_ids"],
            }
            (errors if conflict["values_differ"] else warnings).append(problem)

        counts = {
            table: self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "issuers", "securities", "sources", "security_symbols", "observations",
                "universe_memberships", "corporate_actions",
            )
        }
        return {
            "valid": not errors,
            "schema_version": 1,
            "errors": errors,
            "warnings": warnings,
            "counts": counts,
        }

    def _security_as_of(self, security_id: str, cutoff: str) -> dict | None:
        row = self.connection.execute(
            """
            SELECT sec.security_id, sec.issuer_id, sec.isin, sec.exchange, sec.instrument_type,
                   sym.symbol_id, sym.symbol, sym.valid_from AS symbol_valid_from,
                   sym.valid_to AS symbol_valid_to
            FROM securities AS sec
            LEFT JOIN security_symbols AS sym ON sym.security_id = sec.security_id
                AND (sym.valid_from IS NULL OR sym.valid_from <= ?)
                AND (sym.valid_to IS NULL OR ? < sym.valid_to)
                AND (sym.source_id IS NULL OR EXISTS (
                    SELECT 1 FROM sources AS s WHERE s.source_id = sym.source_id
                        AND s.available_at IS NOT NULL AND s.available_at <= ?
                ))
            WHERE sec.security_id = ?
            ORDER BY sym.symbol_id ASC
            LIMIT 1
            """,
            (cutoff, cutoff, cutoff, security_id),
        ).fetchone()
        return None if row is None else dict(row)

    def _observations_for_fields(
        self, security_id: str, cutoff: str, fields: list[str]
    ) -> list[dict]:
        if not fields:
            return []
        placeholders = ", ".join("?" for _ in fields)
        rows = self.connection.execute(
            f"""
            SELECT o.*
            FROM observations AS o
            JOIN sources AS s ON s.source_id = o.source_id
            WHERE o.security_id = ? AND o.field IN ({placeholders})
              AND o.available_at <= ? AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR ? < o.valid_to)
              AND o.quality_status != 'QUARANTINED'
              AND s.available_at IS NOT NULL AND s.available_at <= ?
            ORDER BY o.field ASC, o.valid_from DESC, o.revision_number DESC, o.observation_id ASC
            """,
            (security_id, *fields, cutoff, cutoff, cutoff, cutoff),
        ).fetchall()
        selected: list[dict] = []
        selected_fields: set[str] = set()
        for row in rows:
            if row["field"] not in selected_fields:
                selected.append(_observation_from_row(row))
                selected_fields.add(row["field"])
        return selected

    def _observation_conflicts(self, security_id: str, cutoff: str, fields: list[str]) -> list[dict]:
        if not fields:
            return []
        placeholders = ", ".join("?" for _ in fields)
        rows = self.connection.execute(
            f"""
            SELECT o.*
            FROM observations AS o
            JOIN sources AS s ON s.source_id = o.source_id
            WHERE o.security_id = ? AND o.field IN ({placeholders})
              AND o.available_at <= ? AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR ? < o.valid_to)
              AND o.quality_status != 'QUARANTINED'
              AND s.available_at IS NOT NULL AND s.available_at <= ?
            ORDER BY o.field ASC, o.valid_from ASC, o.available_at ASC, o.observation_id ASC
            """,
            (security_id, *fields, cutoff, cutoff, cutoff, cutoff),
        ).fetchall()
        grouped = _group_equal_time_observations(rows)
        return [
            {
                "security_id": security_id,
                "field": field,
                "valid_from": valid_from,
                "available_at": [row["available_at"] for row in group],
                "observations": [_observation_from_row(row) for row in group],
            }
            for (_security_id, field, valid_from), group in grouped.items()
            if len(group) > 1
        ]

    def _corporate_actions_as_of(self, security_id: str, cutoff: str) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT ca.* FROM corporate_actions AS ca
            LEFT JOIN sources AS s ON s.source_id = ca.source_id
            WHERE ca.security_id = ? AND ca.available_at IS NOT NULL AND ca.available_at <= ?
              AND (
                  ca.source_id IS NULL
                  OR (s.available_at IS NOT NULL AND s.available_at <= ?)
              )
            ORDER BY ca.action_id ASC
            """,
            (security_id, cutoff, cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def _sources_by_id(self, source_ids: set[str], cutoff: str) -> list[dict]:
        if not source_ids:
            return []
        placeholders = ", ".join("?" for _ in source_ids)
        rows = self.connection.execute(
            f"""
            SELECT * FROM sources
            WHERE source_id IN ({placeholders})
              AND available_at IS NOT NULL AND available_at <= ?
            ORDER BY source_id ASC
            """,
            (*sorted(source_ids), cutoff),
        ).fetchall()
        return [dict(row) for row in rows]

    def _quarantined_count(self, security_id: str, cutoff: str, fields: list[str]) -> int:
        if not fields:
            return 0
        placeholders = ", ".join("?" for _ in fields)
        return self.connection.execute(
            f"""
            SELECT COUNT(*) FROM observations AS o
            JOIN sources AS s ON s.source_id = o.source_id
            WHERE o.security_id = ? AND o.field IN ({placeholders})
              AND o.available_at <= ? AND o.valid_from <= ?
              AND (o.valid_to IS NULL OR ? < o.valid_to)
              AND o.quality_status = 'QUARANTINED'
              AND s.available_at IS NOT NULL AND s.available_at <= ?
            """,
            (security_id, *fields, cutoff, cutoff, cutoff, cutoff),
        ).fetchone()[0]

    def _overlap_problems(
        self,
        table: str,
        identifier: str,
        partition: tuple[str, ...],
        start: str,
        end: str,
        code: str,
    ) -> list[dict]:
        conditions = " AND ".join(f"left_row.{column} = right_row.{column}" for column in partition)
        rows = self.connection.execute(
            f"""
            SELECT left_row.{identifier} AS left_id, right_row.{identifier} AS right_id
            FROM {table} AS left_row
            JOIN {table} AS right_row ON {conditions}
              AND left_row.{identifier} < right_row.{identifier}
              AND (left_row.{end} IS NULL OR right_row.{start} IS NULL OR right_row.{start} < left_row.{end})
              AND (right_row.{end} IS NULL OR left_row.{start} IS NULL OR left_row.{start} < right_row.{end})
            ORDER BY left_row.{identifier} ASC, right_row.{identifier} ASC
            """
        ).fetchall()
        return [{"code": code, "left_id": row["left_id"], "right_id": row["right_id"]} for row in rows]

    def _active_observation_conflicts(self) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT * FROM observations
            WHERE quality_status != 'QUARANTINED' AND valid_to IS NULL
            ORDER BY security_id ASC, field ASC, valid_from ASC, available_at ASC, observation_id ASC
            """
        ).fetchall()
        problems = []
        for (security_id, field, valid_from), group in _group_equal_time_observations(rows).items():
            if len(group) > 1:
                values = {_canonical_observation_value(row) for row in group}
                problems.append({
                    "security_id": security_id,
                    "field": field,
                    "valid_from": valid_from,
                    "available_at": [row["available_at"] for row in group],
                    "observation_ids": [row["observation_id"] for row in group],
                    "values_differ": len(values) > 1,
                })
        return problems

    def _assert_exists(
        self,
        table: str,
        column: str,
        value: str,
        code: str,
        path: str,
    ) -> None:
        row = self.connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} = ?", (value,)
        ).fetchone()
        if row is None:
            raise StoreValidationError(code, path, "Referenced record does not exist")

    def _assert_symbol_interval_available(self, record: SecuritySymbolRecord) -> None:
        overlap = self.connection.execute(
            """
            SELECT 1
            FROM security_symbols
            WHERE security_id = ?
              AND (? IS NULL OR valid_from IS NULL OR valid_from < ?)
              AND (? IS NULL OR valid_to IS NULL OR ? < valid_to)
            LIMIT 1
            """,
            (
                record.security_id,
                record.valid_to,
                record.valid_to,
                record.valid_from,
                record.valid_from,
            ),
        ).fetchone()
        if overlap is not None:
            raise StoreValidationError(
                "SYMBOL_INTERVAL_OVERLAP",
                "record.valid_from",
                "Symbol validity intervals must not overlap",
            )

    def _assert_membership_interval_available(self, record: UniverseMembershipRecord) -> None:
        overlap = self.connection.execute(
            """
            SELECT 1
            FROM universe_memberships
            WHERE universe_id = ? AND security_id = ?
              AND (? IS NULL OR effective_from IS NULL OR effective_from < ?)
              AND (? IS NULL OR effective_to IS NULL OR ? < effective_to)
            LIMIT 1
            """,
            (
                record.universe_id,
                record.security_id,
                record.effective_to,
                record.effective_to,
                record.effective_from,
                record.effective_from,
            ),
        ).fetchone()
        if overlap is not None:
            raise StoreValidationError(
                "MEMBERSHIP_OVERLAP",
                "record.effective_from",
                "Universe membership intervals must not overlap",
            )

    def _raise_foreign_key_error(self, record: Record, error: sqlite3.IntegrityError) -> None:
        if isinstance(record, SecurityRecord):
            raise StoreValidationError("ISSUER_MISSING", "record.issuer_id", "Referenced issuer does not exist") from error
        if isinstance(record, SecuritySymbolRecord):
            security = self.connection.execute(
                "SELECT 1 FROM securities WHERE security_id = ?", (record.security_id,)
            ).fetchone()
            if security is None:
                raise StoreValidationError("SECURITY_MISSING", "record.security_id", "Referenced security does not exist") from error
            raise StoreValidationError("SOURCE_MISSING", "record.source_id", "Referenced source does not exist") from error


def _read_header(path: Path) -> bytes:
    with path.open("rb") as database_file:
        return database_file.read(len(_SQLITE_HEADER))


def _storage_values(record: Record, mapping: _RecordMapping) -> tuple[object, ...]:
    values = {column: getattr(record, column) for column in mapping.columns}
    if isinstance(record, ObservationRecord):
        if record.value_type == "BOOLEAN":
            values["value_number"] = None
            values["value_text"] = "true" if record.value_boolean else "false"
        elif record.value_type == "DATE":
            values["value_number"] = None
            values["value_text"] = record.value_date
        elif record.value_type == "JSON":
            values["value_number"] = None
            values["value_text"] = canonical_json(record.value_json)
    return tuple(values[column] for column in mapping.columns)


def _normalize_fields(fields: list[str] | None) -> list[str] | None:
    if fields is None:
        return None
    if not isinstance(fields, list) or any(not isinstance(field, str) or not field for field in fields):
        raise StoreValidationError("FIELDS_INVALID", "fields", "Fields must be a list of non-empty strings")
    return sorted(set(fields))


def _clock_timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if not isinstance(value, datetime):
        raise StoreValidationError("CLOCK_INVALID", "clock", "Clock must return a datetime")
    return normalize_timestamp(value.isoformat(), "clock")


def _observation_from_row(row: sqlite3.Row) -> dict:
    observation = {
        key: row[key]
        for key in (
            "observation_id", "security_id", "field", "value_type", "value_number",
            "value_text", "unit", "period_start", "period_end", "source_id",
            "available_at", "valid_from", "valid_to", "revision_of", "revision_number",
            "quality_status", "metadata_json", "canonical_json",
        )
    }
    observation["value"] = _query_value(observation)
    return observation


def _group_equal_time_observations(rows: list[sqlite3.Row]) -> dict[tuple[str, str, str], list[sqlite3.Row]]:
    groups: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = (row["security_id"], row["field"], row["valid_from"])
        groups.setdefault(key, []).append(row)
    return groups


def _canonical_observation_value(row: sqlite3.Row) -> str:
    return canonical_json({
        "value_type": row["value_type"],
        "value_number": row["value_number"],
        "value_text": row["value_text"],
        "unit": row["unit"],
    })


def _query_value(observation: dict) -> object:
    value_type = observation["value_type"]
    if value_type == "NUMBER":
        return observation["value_number"]
    if value_type == "TEXT" or value_type == "DATE":
        return observation["value_text"]
    if value_type == "BOOLEAN":
        return observation["value_text"] == "true"
    if value_type == "JSON":
        return json.loads(observation["value_text"])
    raise ValueError(f"Unsupported stored observation value type: {value_type}")
