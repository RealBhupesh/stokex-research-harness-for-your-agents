# STOCKEX Point-in-Time Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free SQLite evidence store that reconstructs exactly what STOCKEX could know at a historical decision timestamp.

**Architecture:** A standard-library Python package validates immutable typed records, persists them transactionally in SQLite, and exposes deterministic as-of, universe, evidence-packet and integrity queries. A JSONL importer and CLI sit above the store; the existing evidence-room skill consumes exported packets without absorbing database logic.

**Tech Stack:** Python 3.10+, `sqlite3`, `dataclasses`, `datetime`, `json`, `argparse`, `hashlib`, `pathlib`, `unittest`

**Spec:** `docs/superpowers/specs/2026-09-15-point-in-time-data-foundation-design.md`

## Global Constraints

- Use only the Python standard library.
- Store every comparison timestamp as timezone-aware normalized UTC ISO 8601 text.
- Never select evidence whose `available_at` is after the requested cutoff.
- Preserve original and revised values as separate immutable observation rows.
- Use stable security identifiers or ISINs for joins, never ticker alone.
- Use parameterized SQL and transactional imports.
- Runtime databases and generated packets must remain untracked.
- Ship only synthetic fixtures; do not redistribute licensed market data.
- Passing integrity checks proves internal consistency, not source authenticity, completeness or predictive power.
- Keep every existing test green when repository integration is complete.

## File Structure

```text
stockex/
├── __init__.py                 Public package version
├── cli.py                      JSON command-line interface
└── store/
    ├── __init__.py             Store exports
    ├── schema.py               SQLite schema and migrations
    ├── records.py              Dataclasses and validation
    ├── database.py             Persistence and historical queries
    └── importer.py             Atomic JSONL import
tests/
├── test_store_schema.py
├── test_store_records.py
├── test_store_database.py
├── test_store_queries.py
└── test_store_cli.py
```

---

### Task 1: Versioned SQLite Schema

**Files:**
- Create: `stockex/__init__.py`
- Create: `stockex/store/__init__.py`
- Create: `stockex/store/schema.py`
- Create: `tests/test_store_schema.py`

**Interfaces:**
- Consumes: Python standard-library `sqlite3.Connection`.
- Produces: `SCHEMA_VERSION`, `initialize_database(connection)` and `current_schema_version(connection)`.

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_store_schema.py` with temporary in-memory connections and these tests:

```python
import sqlite3
import unittest

from stockex.store.schema import SCHEMA_VERSION, current_schema_version, initialize_database


class StoreSchemaTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_initializes_all_tables_and_version(self):
        initialize_database(self.connection)
        names = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue({
            "schema_migrations", "issuers", "securities", "security_symbols",
            "sources", "observations", "universe_memberships", "corporate_actions",
        } <= names)
        self.assertEqual(current_schema_version(self.connection), SCHEMA_VERSION)

    def test_initialization_is_idempotent_and_foreign_keys_are_enabled(self):
        initialize_database(self.connection)
        initialize_database(self.connection)
        self.assertEqual(self.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(
            self.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python -m unittest tests.test_store_schema -v
```

Expected: import failure because `stockex.store.schema` does not exist.

- [ ] **Step 3: Implement the package and first migration**

Create `stockex/__init__.py`:

```python
"""STOCKEX deterministic research infrastructure."""

__version__ = "4.0.0-dev1"
```

Create `stockex/store/__init__.py`:

```python
"""Point-in-time evidence storage."""

from .schema import SCHEMA_VERSION, current_schema_version, initialize_database

__all__ = ["SCHEMA_VERSION", "current_schema_version", "initialize_database"]
```

Create `stockex/store/schema.py` with `SCHEMA_VERSION = 1`. `initialize_database` must enable foreign keys and WAL, create `schema_migrations`, then create the seven domain tables inside one transaction. Use these primary and foreign-key relationships:

```sql
issuers(issuer_id PRIMARY KEY, legal_name, cin, lei, status, metadata_json, canonical_json)
securities(security_id PRIMARY KEY, issuer_id REFERENCES issuers, isin UNIQUE, exchange, instrument_type, canonical_json)
security_symbols(symbol_id PRIMARY KEY, security_id REFERENCES securities, symbol, valid_from, valid_to, source_id REFERENCES sources, canonical_json)
sources(source_id PRIMARY KEY, publisher, source_class, uri, published_at, available_at, retrieved_at, content_hash, metadata_json, canonical_json)
observations(observation_id PRIMARY KEY, security_id REFERENCES securities, field, value_type, value_number, value_text, unit, period_start, period_end, source_id REFERENCES sources, available_at, valid_from, valid_to, revision_of REFERENCES observations, revision_number, quality_status, metadata_json, canonical_json)
universe_memberships(membership_id PRIMARY KEY, universe_id, security_id REFERENCES securities, effective_from, effective_to, source_id REFERENCES sources, metadata_json, canonical_json)
corporate_actions(action_id PRIMARY KEY, security_id REFERENCES securities, action_type, source_id REFERENCES sources, available_at, ex_date, record_date, effective_date, ratio, cash_amount, currency, status, metadata_json, canonical_json)
```

Add checks for controlled exchange, issuer status, observation value type, observation quality status, non-negative revision numbers, interval ordering and exactly one observation value representation. `current_schema_version` returns zero before initialization and the maximum applied version afterward.

- [ ] **Step 4: Run the schema tests and full regression suite**

Run:

```bash
python -m unittest tests.test_store_schema -v
python -m unittest discover -s tests -v
```

Expected: schema tests pass. The repository-integrity manifest test may remain red until Task 7 because newly planned files are intentionally not listed before integration; no behavioral test may fail.

- [ ] **Step 5: Commit the schema**

```bash
git add stockex/__init__.py stockex/store/__init__.py stockex/store/schema.py tests/test_store_schema.py
git commit -m "Build versioned point-in-time schema"
```

---

### Task 2: Typed Records and Deterministic Validation

**Files:**
- Create: `stockex/store/records.py`
- Create: `tests/test_store_records.py`
- Modify: `stockex/store/__init__.py`

**Interfaces:**
- Consumes: JSON-compatible envelope dictionaries.
- Produces: `StoreValidationError`, six immutable record dataclasses, `normalize_timestamp`, `canonical_json` and `validate_envelope`.

- [ ] **Step 1: Write failing validation tests**

Create `tests/test_store_records.py`:

```python
import unittest

from stockex.store.records import StoreValidationError, canonical_json, normalize_timestamp, validate_envelope


class StoreRecordTests(unittest.TestCase):
    def test_normalizes_timezone_aware_timestamp_to_utc(self):
        self.assertEqual(
            normalize_timestamp("2026-05-15T18:04:21+05:30", "available_at"),
            "2026-05-15T12:34:21Z",
        )

    def test_rejects_naive_timestamp_with_stable_code(self):
        with self.assertRaises(StoreValidationError) as caught:
            normalize_timestamp("2026-05-15T18:04:21", "available_at")
        self.assertEqual(caught.exception.code, "TIMESTAMP_NAIVE")

    def test_canonical_json_is_stable(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_rejects_number_without_unit(self):
        envelope = {
            "record_type": "observation",
            "schema_version": 1,
            "record": {
                "observation_id": "obs1", "security_id": "sec1",
                "field": "financial.revenue", "value_type": "NUMBER",
                "value_number": 100, "source_id": "src1",
                "available_at": "2026-05-15T18:04:21+05:30",
                "valid_from": "2026-05-15T18:04:21+05:30",
                "revision_number": 0, "quality_status": "VERIFIED",
            },
        }
        with self.assertRaises(StoreValidationError) as caught:
            validate_envelope(envelope)
        self.assertEqual(caught.exception.code, "UNIT_REQUIRED")

    def test_rejects_invalid_interval(self):
        envelope = {
            "record_type": "security_symbol", "schema_version": 1,
            "record": {
                "symbol_id": "sym1", "security_id": "sec1", "symbol": "EXAMPLE",
                "valid_from": "2026-06-01T00:00:00Z",
                "valid_to": "2026-05-01T00:00:00Z",
            },
        }
        with self.assertRaises(StoreValidationError) as caught:
            validate_envelope(envelope)
        self.assertEqual(caught.exception.code, "INTERVAL_INVALID")
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
python -m unittest tests.test_store_records -v
```

Expected: import failure because `stockex.store.records` does not exist.

- [ ] **Step 3: Implement validation and immutable records**

In `records.py`, implement:

```python
class StoreValidationError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


def normalize_timestamp(value: str, path: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise StoreValidationError("TIMESTAMP_NAIVE", path, "Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
```

Define frozen dataclasses named `IssuerRecord`, `SecurityRecord`, `SecuritySymbolRecord`, `SourceRecord`, `ObservationRecord`, `UniverseMembershipRecord` and `CorporateActionRecord`. Define `Record` as their union. `validate_envelope(envelope: dict) -> Record` must enforce schema version 1, supported record types, required non-empty identifiers, controlled enums, timezone-aware timestamps, valid half-open intervals, exactly one typed value representation, numeric units, metadata size no greater than 64 KiB and nesting no deeper than 12 levels. A source must satisfy `published_at <= available_at <= retrieved_at` whenever all relevant timestamps are present. Normalize metadata through `canonical_json`.

Export the public record symbols from `stockex/store/__init__.py`.

- [ ] **Step 4: Run focused and regression tests**

```bash
python -m unittest tests.test_store_records -v
python -m unittest tests.test_store_schema tests.test_store_records -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit record validation**

```bash
git add stockex/store/__init__.py stockex/store/records.py tests/test_store_records.py
git commit -m "Validate immutable evidence records"
```

---

### Task 3: Identity, Symbol and Source Ingestion

**Files:**
- Create: `stockex/store/database.py`
- Create: `tests/test_store_database.py`
- Modify: `stockex/store/__init__.py`

**Interfaces:**
- Consumes: validated `Record` instances from Task 2 and the schema from Task 1.
- Produces: `IngestResult` and `PointInTimeStore.open`, `close`, context-manager and `ingest` behavior for issuers, securities, symbols and sources.

- [ ] **Step 1: Write failing persistence tests**

Create `tests/test_store_database.py` with helpers that produce valid envelopes, then add:

```python
import pathlib
import tempfile
import unittest

from stockex.store.database import PointInTimeStore
from stockex.store.records import StoreValidationError, validate_envelope


class StoreDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / "stockex.sqlite3"
        self.store = PointInTimeStore.open(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_ingests_dependencies_and_replays_idempotently(self):
        first = self.store.ingest(validate_envelope(issuer_envelope()))
        second = self.store.ingest(validate_envelope(issuer_envelope()))
        self.assertEqual(first.status, "INSERTED")
        self.assertEqual(second.status, "UNCHANGED")

    def test_rejects_same_id_with_different_content(self):
        self.store.ingest(validate_envelope(issuer_envelope()))
        changed = issuer_envelope()
        changed["record"]["legal_name"] = "Changed Limited"
        with self.assertRaises(StoreValidationError) as caught:
            self.store.ingest(validate_envelope(changed))
        self.assertEqual(caught.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_enforces_foreign_keys(self):
        with self.assertRaises(StoreValidationError) as caught:
            self.store.ingest(validate_envelope(security_envelope()))
        self.assertEqual(caught.exception.code, "ISSUER_MISSING")

    def test_rejects_overlapping_symbol_intervals(self):
        ingest_identity_fixture(self.store)
        self.store.ingest(validate_envelope(symbol_envelope("sym1", "2020-01-01T00:00:00Z", None)))
        with self.assertRaises(StoreValidationError) as caught:
            self.store.ingest(validate_envelope(symbol_envelope("sym2", "2021-01-01T00:00:00Z", None)))
        self.assertEqual(caught.exception.code, "SYMBOL_INTERVAL_OVERLAP")
```

The helper envelopes must use synthetic values: issuer `issuer_example`, security `INE000A01001`, symbol `EXAMPLE`, exchange `NSE` and source `src_exchange_1`.

- [ ] **Step 2: Run the tests and verify RED**

```bash
python -m unittest tests.test_store_database -v
```

Expected: import failure because `stockex.store.database` does not exist.

- [ ] **Step 3: Implement safe persistence**

Implement the `IngestResult` value object:

```python
@dataclass(frozen=True)
class IngestResult:
    record_type: str
    record_id: str
    status: str  # INSERTED or UNCHANGED
```

Implement `PointInTimeStore.open(path, *, clock=None)`, `close()`, `__enter__()`, `__exit__()`, `transaction()` and `ingest(record, *, commit=True)`. `open` must refuse an existing file whose SQLite header is invalid, refuse a missing parent directory, initialize the schema, set `row_factory = sqlite3.Row`, enable foreign keys and use a five-second busy timeout. The optional clock is a zero-argument callable returning an aware `datetime`; default it to UTC now. Each ingest uses the dataclass's canonical representation and parameterized SQL. Existing identical IDs return `UNCHANGED`; existing different IDs raise `IDEMPOTENCY_CONFLICT`. Translate foreign-key failures to `ISSUER_MISSING`, `SECURITY_MISSING` or `SOURCE_MISSING`. Detect overlapping half-open symbol intervals before insert. `transaction()` commits exactly once on success and rolls back on every exception; the importer calls `ingest(record, commit=False)` inside it.

- [ ] **Step 4: Run focused and cumulative tests**

```bash
python -m unittest tests.test_store_database -v
python -m unittest tests.test_store_schema tests.test_store_records tests.test_store_database -v
```

Expected: all cumulative store tests pass.

- [ ] **Step 5: Commit persistence**

```bash
git add stockex/store/__init__.py stockex/store/database.py tests/test_store_database.py
git commit -m "Persist point-in-time identities and sources"
```

---

### Task 4: Observation Revisions and As-Of Queries

**Files:**
- Modify: `stockex/store/database.py`
- Create: `tests/test_store_queries.py`

**Interfaces:**
- Consumes: `ObservationRecord` and stored issuer/security/source dependencies.
- Produces: revision-chain ingestion and `observation_as_of(security_id, field, cutoff)`.

- [ ] **Step 1: Write failing revision and cutoff tests**

Create `tests/test_store_queries.py` with a temporary store and dependency fixtures, then add:

```python
class ObservationQueryTests(unittest.TestCase):
    def test_original_before_revision_and_revision_after_availability(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        self.ingest_observation(
            "obs_v1", 92.0, "2026-06-10T09:00:00Z", revision_of="obs_v0", revision_number=1
        )
        before = self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-06-01T00:00:00Z"
        )
        after = self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-06-11T00:00:00Z"
        )
        self.assertEqual(before["observation_id"], "obs_v0")
        self.assertEqual(after["observation_id"], "obs_v1")

    def test_excludes_future_and_quarantined_records(self):
        self.ingest_observation(
            "future", 100.0, "2027-01-01T00:00:00Z", revision_of=None, revision_number=0
        )
        self.assertIsNone(self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-12-31T23:59:59Z"
        ))

    def test_rejects_broken_revision_chain(self):
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v2", 90.0, "2026-06-12T00:00:00Z",
                revision_of="missing", revision_number=2,
            )
        self.assertEqual(caught.exception.code, "REVISION_PARENT_MISSING")
```

Also test wrong security or field in the parent, non-sequential revision number, revision availability earlier than its parent and a naive query cutoff.

- [ ] **Step 2: Run the tests and verify RED**

```bash
python -m unittest tests.test_store_queries.ObservationQueryTests -v
```

Expected: failure because observation ingestion and `observation_as_of` are incomplete.

- [ ] **Step 3: Implement revisions and historical selection**

On observation ingestion:

```text
original: revision_of IS NULL AND revision_number = 0
revision: parent exists
revision.security_id == parent.security_id
revision.field == parent.field
revision.revision_number == parent.revision_number + 1
revision.available_at >= parent.available_at
```

When inserting a revision, update only the parent's database-maintained `valid_to` to the revision's `valid_from`; never mutate its analytical value, source, availability, canonical input or revision identity. Reject a revision whose start would create a negative interval.

Implement `observation_as_of` with parameterized conditions:

```sql
WHERE security_id = ? AND field = ?
  AND available_at <= ? AND valid_from <= ?
  AND (valid_to IS NULL OR ? < valid_to)
  AND quality_status != 'QUARANTINED'
ORDER BY valid_from DESC, revision_number DESC, observation_id ASC
```

Return a JSON-compatible dictionary containing the selected observation and its source provenance. Return `None` when no eligible row exists.

- [ ] **Step 4: Run focused and cumulative tests**

```bash
python -m unittest tests.test_store_queries.ObservationQueryTests -v
python -m unittest tests.test_store_schema tests.test_store_records tests.test_store_database tests.test_store_queries -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit historical observations**

```bash
git add stockex/store/database.py tests/test_store_queries.py
git commit -m "Query immutable observation vintages"
```

---

### Task 5: Historical Universes, Corporate Actions, Evidence Packets and Integrity

**Files:**
- Modify: `stockex/store/database.py`
- Modify: `tests/test_store_queries.py`

**Interfaces:**
- Consumes: universe-membership and corporate-action records plus Task 4 observation queries.
- Produces: `universe_as_of`, `evidence_packet` and `integrity_report`.

- [ ] **Step 1: Write failing universe and packet tests**

Append these test classes to `tests/test_store_queries.py`:

```python
class UniverseQueryTests(StoreFixture):
    def test_reconstructs_membership_at_cutoff(self):
        self.ingest_membership("m1", "NIFTY_TEST", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
        self.assertEqual(
            [row["security_id"] for row in self.store.universe_as_of("NIFTY_TEST", "2025-06-01T00:00:00Z")],
            ["INE000A01001"],
        )
        self.assertEqual(self.store.universe_as_of("NIFTY_TEST", "2026-06-01T00:00:00Z"), [])

    def test_rejects_overlapping_memberships(self):
        self.ingest_membership("m1", "NIFTY_TEST", "2025-01-01T00:00:00Z", None)
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_membership("m2", "NIFTY_TEST", "2025-06-01T00:00:00Z", None)
        self.assertEqual(caught.exception.code, "MEMBERSHIP_OVERLAP")


class EvidencePacketTests(StoreFixture):
    def test_packet_is_ordered_and_contains_provenance_and_actions(self):
        self.ingest_two_fields_in_reverse_order()
        self.ingest_corporate_action()
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual([row["field"] for row in packet["observations"]], sorted(
            row["field"] for row in packet["observations"]
        ))
        self.assertEqual(packet["sources"][0]["source_id"], "src_exchange_1")
        self.assertEqual(packet["corporate_actions"][0]["action_id"], "action1")
        self.assertTrue(packet["integrity"]["strict_point_in_time"])

    def test_integrity_report_is_clean_for_valid_store(self):
        report = self.store.integrity_report()
        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])
```

Also test field filtering, exclusion of post-cutoff corporate actions, stable source deduplication, `generated_at` isolation, equal-time conflicts and integrity detection for foreign-key, interval and revision-chain corruption created only after temporarily disabling checks in the fixture.

- [ ] **Step 2: Run the new tests and verify RED**

```bash
python -m unittest tests.test_store_queries.UniverseQueryTests tests.test_store_queries.EvidencePacketTests -v
```

Expected: failures because the three public query methods are absent.

- [ ] **Step 3: Implement universe and evidence queries**

Implement the exact public methods `universe_as_of(self, universe_id: str, cutoff: str) -> list[dict]`, `evidence_packet(self, security_id: str, cutoff: str, fields: list[str] | None = None) -> dict` and `integrity_report(self) -> dict`.

`universe_as_of` uses inclusive `effective_from` and exclusive `effective_to`, joins stable security and cutoff-valid symbol rows and sorts by security ID. Reject overlapping membership intervals during ingestion.

`evidence_packet` selects the latest eligible non-quarantined record for each requested field, adds equal-time competing records to `conflicts`, includes only corporate actions whose `available_at <= cutoff`, deduplicates sources by ID and sorts every collection deterministically. It must report missing requested fields in `gaps` and count excluded quarantined records. Use an injectable clock defaulting to aware UTC now so tests can freeze `generated_at`.

`integrity_report` returns:

```json
{
  "valid": true,
  "schema_version": 1,
  "errors": [],
  "warnings": [],
  "counts": {}
}
```

Run `PRAGMA foreign_key_check` and deterministic SQL checks for invalid intervals, broken or non-sequential revision chains, overlapping symbols, overlapping memberships and equal-time conflicting active observations. Conflicts are warnings unless their canonical values differ for the same security, field and validity timestamp, in which case they are errors requiring analyst resolution.

- [ ] **Step 4: Run cumulative store tests**

```bash
python -m unittest tests.test_store_schema tests.test_store_records tests.test_store_database tests.test_store_queries -v
```

Expected: all store tests pass.

- [ ] **Step 5: Commit query and integrity behavior**

```bash
git add stockex/store/database.py tests/test_store_queries.py
git commit -m "Reconstruct historical evidence packets"
```

---

### Task 6: Atomic JSONL Importer and JSON CLI

**Files:**
- Create: `stockex/store/importer.py`
- Create: `stockex/cli.py`
- Create: `tests/test_store_cli.py`
- Modify: `stockex/store/__init__.py`

**Interfaces:**
- Consumes: JSONL envelopes and the complete `PointInTimeStore` API.
- Produces: `ImportErrorDetail`, `import_jsonl(store, path)` and CLI commands `init`, `ingest`, `as-of`, `universe`, `packet`, `integrity`.

- [ ] **Step 1: Write failing atomic-import and CLI tests**

Create `tests/test_store_cli.py`:

```python
import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from stockex.cli import main
from stockex.store.database import PointInTimeStore
from stockex.store.importer import ImportFailure, import_jsonl


class JsonlImportTests(unittest.TestCase):
    def test_invalid_line_rolls_back_complete_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            database = root / "test.sqlite3"
            source = root / "records.jsonl"
            source.write_text(
                json.dumps(issuer_envelope()) + "\n" + "{invalid json}\n",
                encoding="utf-8",
            )
            with PointInTimeStore.open(database) as store:
                with self.assertRaises(ImportFailure) as caught:
                    import_jsonl(store, source)
                self.assertEqual(caught.exception.line, 2)
                count = store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0]
                self.assertEqual(count, 0)


class CliTests(unittest.TestCase):
    def test_init_outputs_json(self):
        with tempfile.TemporaryDirectory() as directory:
            database = pathlib.Path(directory) / "test.sqlite3"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["init", str(database)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)

    def test_validation_error_is_structured_json(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = main(["as-of", "missing.sqlite3", "sec", "field", "--cutoff", "not-a-time"])
        self.assertNotEqual(code, 0)
        self.assertIn("code", json.loads(error.getvalue()))
```

Add one successful test for every CLI command using a valid synthetic fixture. Call `main(argv: list[str] | None = None) -> int` directly so tests do not spawn processes.

- [ ] **Step 2: Run the tests and verify RED**

```bash
python -m unittest tests.test_store_cli -v
```

Expected: import failure because the importer and CLI do not exist.

- [ ] **Step 3: Implement the transactional importer**

Implement:

```python
@dataclass(frozen=True)
class ImportFailure(Exception):
    path: str
    line: int
    code: str
    message: str


def import_jsonl(store: PointInTimeStore, path: str | pathlib.Path) -> dict:
    """Validate and ingest one complete JSONL file in a single transaction."""
```

The importer reads UTF-8 line by line, rejects blank records, decodes JSON, calls `validate_envelope`, then calls `store.ingest(record, commit=False)` inside `store.transaction()`. It rolls back on any error and returns counts for `INSERTED` and `UNCHANGED`. Convert JSON errors to `JSON_INVALID` and include the one-based line number.

- [ ] **Step 4: Implement the CLI**

Build `argparse` subcommands matching the spec. Every command returns an integer. The module entry point uses `raise SystemExit(main())`. Serialize each command's `payload` with `json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)`. Map validation, import, filesystem and SQLite failures to stable JSON errors without tracebacks by default. The `init` command refuses a non-SQLite existing file. Query commands open the database read-write in this release because initialization checks require the migration table, but they never mutate analytical records.

- [ ] **Step 5: Run focused and full behavioral tests**

```bash
python -m unittest tests.test_store_cli -v
python -m unittest tests.test_store_schema tests.test_store_records tests.test_store_database tests.test_store_queries tests.test_store_cli -v
```

Expected: all point-in-time subsystem tests pass.

- [ ] **Step 6: Commit importer and CLI**

```bash
git add stockex/store/__init__.py stockex/store/importer.py stockex/cli.py tests/test_store_cli.py
git commit -m "Add atomic evidence imports and CLI"
```

---

### Task 7: STOCKEX Skill, Documentation and Repository Integration

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `QUICKSTART.md`
- Modify: `SKILL.md`
- Modify: `skills/india-equity-evidence-room/SKILL.md`
- Modify: `references/point-in-time.md`
- Modify: `scripts/USAGE.md`
- Modify: `manifest.json`
- Modify: `tests/test_repository_integrity.py`

**Interfaces:**
- Consumes: the complete CLI and evidence-packet contract from Tasks 1 through 6.
- Produces: user-facing setup, agent routing, runtime exclusions, exact manifest coverage and release verification.

- [ ] **Step 1: Read the skill-authoring requirements before modifying skills**

Use the `skill-creator` and `superpowers:writing-skills` instructions because this task changes two skill entrypoints. Preserve their YAML names and descriptions unless the new executable capability materially requires a description change.

- [ ] **Step 2: Write failing integration assertions**

Extend `tests/test_repository_integrity.py`:

```python
def test_point_in_time_runtime_is_shipped_and_documented(self):
    required = {
        "stockex/__init__.py",
        "stockex/cli.py",
        "stockex/store/__init__.py",
        "stockex/store/schema.py",
        "stockex/store/records.py",
        "stockex/store/database.py",
        "stockex/store/importer.py",
        "docs/superpowers/specs/2026-09-15-point-in-time-data-foundation-design.md",
        "docs/superpowers/plans/2026-09-15-point-in-time-data-foundation.md",
    }
    self.assertTrue(required <= shipped_files())
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    self.assertIn("python -m stockex.cli", readme)
    self.assertIn("point-in-time", readme.lower())


def test_runtime_databases_are_ignored(self):
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.sqlite", "*.sqlite3", "*.db"):
        self.assertIn(pattern, ignore)
```

- [ ] **Step 3: Run the integration tests and verify RED**

```bash
python -m unittest tests.test_repository_integrity -v
```

Expected: documentation command and ignore-pattern assertions fail.

- [ ] **Step 4: Integrate the runtime into the skills and documentation**

Update documentation with exact commands:

```bash
python -m stockex.cli init research.sqlite3
python -m stockex.cli ingest research.sqlite3 evidence.jsonl
python -m stockex.cli packet research.sqlite3 INE000A01001 --cutoff 2026-06-01T10:00:00+05:30
python -m stockex.cli integrity research.sqlite3
```

In the root and evidence-room skills, require a generated point-in-time packet when a database is supplied. Preserve the manual evidence-ledger fallback when no database exists. Explicitly state that a clean integrity report does not establish source authenticity, dataset completeness or investment suitability.

Add `*.sqlite`, `*.sqlite3`, `*.db`, `evidence-packet-*.json` and `stockex-output/` to `.gitignore`. Update `manifest.json` to version `4.0.0-dev1`, change the data-integration statement to describe the offline store accurately, preserve the unbacktested performance warning and list every shipped file exactly once in sorted order.

- [ ] **Step 5: Validate both modified skills**

Run the skill validator specified by the installed `skill-creator` instructions on:

```text
SKILL.md
skills/india-equity-evidence-room/SKILL.md
```

Expected: both skill entrypoints pass metadata and structural validation.

- [ ] **Step 6: Run final verification**

```bash
python -m unittest discover -s tests -v
python -m stockex.cli init /tmp/stockex-verification.sqlite3
python -m stockex.cli integrity /tmp/stockex-verification.sqlite3
python -m compileall -q stockex scripts tests
python -m json.tool manifest.json >/dev/null
python -m json.tool schema/decision-packet.schema.json >/dev/null
git diff --check
git status --short
```

Expected: every test passes; CLI integrity output has `"valid": true`; Python compilation, JSON parsing and whitespace checks pass. Remove only the explicitly named `/tmp/stockex-verification.sqlite3` after verification.

- [ ] **Step 7: Commit the integrated subsystem**

```bash
git add .gitignore README.md QUICKSTART.md SKILL.md skills/india-equity-evidence-room/SKILL.md references/point-in-time.md scripts/USAGE.md manifest.json tests/test_repository_integrity.py
git commit -m "Integrate point-in-time evidence foundation"
```

- [ ] **Step 8: Publish the completed commits to the existing pull request**

Use the authorized GitHub connection to update `feat/stockex-v3` without force-pushing `main`. Verify the remote recursive tree against the local tracked tree and confirm pull request #1 remains open and mergeable.

## Completion Criteria

- All seven tasks are committed on `feat/stockex-v3`.
- Full tests pass with no manifest exception.
- Both modified skills validate.
- A synthetic database can be initialized, populated, queried and integrity-checked offline.
- An original filing is returned before its revision timestamp and the revision is returned afterward.
- Invalid JSONL input rolls back atomically.
- GitHub pull request #1 contains the exact verified local tree.
