import pathlib
import tempfile
import unittest

from stockex.store.database import PointInTimeStore
from stockex.store.records import StoreValidationError, validate_envelope


def issuer_envelope():
    return {
        "schema_version": 1,
        "record_type": "issuer",
        "record": {
            "issuer_id": "issuer_example",
            "legal_name": "Example Limited",
            "status": "ACTIVE",
        },
    }


def security_envelope():
    return {
        "schema_version": 1,
        "record_type": "security",
        "record": {
            "security_id": "INE000A01001",
            "issuer_id": "issuer_example",
            "isin": "INE000A01001",
            "exchange": "NSE",
            "instrument_type": "EQUITY",
        },
    }


def source_envelope():
    return {
        "schema_version": 1,
        "record_type": "source",
        "record": {
            "source_id": "src_exchange_1",
            "publisher": "Example Exchange",
            "source_class": "EXCHANGE",
        },
    }


def symbol_envelope(symbol_id, valid_from, valid_to, symbol="EXAMPLE"):
    return {
        "schema_version": 1,
        "record_type": "security_symbol",
        "record": {
            "symbol_id": symbol_id,
            "security_id": "INE000A01001",
            "symbol": symbol,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "source_id": "src_exchange_1",
        },
    }


def ingest_identity_fixture(store):
    store.ingest(validate_envelope(issuer_envelope()))
    store.ingest(validate_envelope(security_envelope()))
    store.ingest(validate_envelope(source_envelope()))


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

    def test_transaction_rolls_back_default_ingests(self):
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.ingest(validate_envelope(issuer_envelope()))
                raise RuntimeError("force rollback")
        count = self.store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0]
        self.assertEqual(count, 0)

    def test_rejects_overlapping_intervals_after_ticker_change(self):
        ingest_identity_fixture(self.store)
        self.store.ingest(
            validate_envelope(symbol_envelope("sym1", "2020-01-01T00:00:00Z", "2022-01-01T00:00:00Z"))
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.store.ingest(
                validate_envelope(
                    symbol_envelope("sym2", "2021-01-01T00:00:00Z", None, symbol="RENAMED")
                )
            )
        self.assertEqual(caught.exception.code, "SYMBOL_INTERVAL_OVERLAP")


if __name__ == "__main__":
    unittest.main()
