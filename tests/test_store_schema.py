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

    def test_rejects_noncanonical_comparison_timestamps(self):
        initialize_database(self.connection)
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO sources(source_id, available_at) VALUES (?, ?)",
                ("bad-source", "not-a-utc-timestamp"),
            )

    def test_observations_are_append_only_except_valid_to_closure(self):
        initialize_database(self.connection)
        self.connection.execute("INSERT INTO issuers(issuer_id) VALUES ('issuer-1')")
        self.connection.execute(
            "INSERT INTO securities(security_id, issuer_id) VALUES ('security-1', 'issuer-1')"
        )
        self.connection.execute("INSERT INTO sources(source_id) VALUES ('source-1')")
        self.connection.execute(
            """INSERT INTO observations(
                observation_id, security_id, source_id, value_type, value_number
            ) VALUES ('observation-1', 'security-1', 'source-1', 'NUMBER', 1)"""
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE observations SET value_number = 2 WHERE observation_id = 'observation-1'"
            )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "DELETE FROM observations WHERE observation_id = 'observation-1'"
            )
        self.connection.execute(
            "UPDATE observations SET valid_to = '2026-09-15T12:34:56Z' "
            "WHERE observation_id = 'observation-1'"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "UPDATE observations SET valid_to = '2026-09-16T12:34:56Z' "
                "WHERE observation_id = 'observation-1'"
            )

    def test_upgrades_legacy_v1_schema_and_enforces_timestamps(self):
        self.connection.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT);
            INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-09-15 00:00:00');
            CREATE TABLE issuers(issuer_id TEXT PRIMARY KEY, legal_name TEXT, cin TEXT, lei TEXT, status TEXT, metadata_json TEXT, canonical_json TEXT);
            CREATE TABLE sources(source_id TEXT PRIMARY KEY, publisher TEXT, source_class TEXT, uri TEXT, published_at TEXT, available_at TEXT, retrieved_at TEXT, content_hash TEXT, metadata_json TEXT, canonical_json TEXT);
            CREATE TABLE securities(security_id TEXT PRIMARY KEY, issuer_id TEXT, isin TEXT UNIQUE, exchange TEXT, instrument_type TEXT, canonical_json TEXT);
            CREATE TABLE security_symbols(symbol_id TEXT PRIMARY KEY, security_id TEXT, symbol TEXT, valid_from TEXT, valid_to TEXT, source_id TEXT, canonical_json TEXT);
            CREATE TABLE observations(observation_id TEXT PRIMARY KEY, security_id TEXT, field TEXT, value_type TEXT, value_number REAL, value_text TEXT, unit TEXT, period_start TEXT, period_end TEXT, source_id TEXT, available_at TEXT, valid_from TEXT, valid_to TEXT, revision_of TEXT, revision_number INTEGER, quality_status TEXT, metadata_json TEXT, canonical_json TEXT);
            CREATE TABLE universe_memberships(membership_id TEXT PRIMARY KEY, universe_id TEXT, security_id TEXT, effective_from TEXT, effective_to TEXT, source_id TEXT, metadata_json TEXT, canonical_json TEXT);
            CREATE TABLE corporate_actions(action_id TEXT PRIMARY KEY, security_id TEXT, action_type TEXT, source_id TEXT, available_at TEXT, ex_date TEXT, record_date TEXT, effective_date TEXT, ratio REAL, cash_amount REAL, currency TEXT, status TEXT, metadata_json TEXT, canonical_json TEXT);
            """
        )
        initialize_database(self.connection)
        self.assertEqual(current_schema_version(self.connection), 2)
        self.assertEqual(
            self.connection.execute(
                "SELECT applied_at FROM schema_migrations WHERE version = 1"
            ).fetchone()[0],
            "2026-09-15T00:00:00Z",
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO sources(source_id, available_at) VALUES ('legacy-bad', 'after-any-cutoff')"
            )

    def test_legacy_upgrade_rejects_invalid_existing_rows_transactionally(self):
        self.connection.executescript(
            """
            CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT);
            INSERT INTO schema_migrations(version, applied_at) VALUES (1, '2026-09-15 00:00:00');
            CREATE TABLE sources(source_id TEXT PRIMARY KEY, published_at TEXT, available_at TEXT, retrieved_at TEXT);
            INSERT INTO sources(source_id, available_at) VALUES ('legacy-bad', 'after-any-cutoff');
            """
        )
        original_objects = self.connection.execute("SELECT * FROM sqlite_master ORDER BY type, name").fetchall()
        original_migrations = self.connection.execute("SELECT * FROM schema_migrations").fetchall()
        original_sources = self.connection.execute("SELECT * FROM sources").fetchall()
        with self.assertRaises(sqlite3.IntegrityError):
            initialize_database(self.connection)
        self.assertEqual(current_schema_version(self.connection), 1)
        self.assertEqual(self.connection.execute("SELECT * FROM sqlite_master ORDER BY type, name").fetchall(), original_objects)
        self.assertEqual(self.connection.execute("SELECT * FROM schema_migrations").fetchall(), original_migrations)
        self.assertEqual(self.connection.execute("SELECT * FROM sources").fetchall(), original_sources)


if __name__ == "__main__":
    unittest.main()
