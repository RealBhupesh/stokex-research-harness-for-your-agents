import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from stockex.cli import main
from stockex.store.database import PointInTimeStore
from stockex.store.importer import ImportFailure, import_jsonl
from stockex.store.schema import SCHEMA_VERSION


def envelope(record_type, record):
    return {"schema_version": 1, "record_type": record_type, "record": record}


def synthetic_envelopes():
    return [
        envelope("issuer", {"issuer_id": "issuer_example", "legal_name": "Example Limited"}),
        envelope("security", {"security_id": "SEC_EXAMPLE", "issuer_id": "issuer_example", "exchange": "NSE"}),
        envelope("source", {"source_id": "source_example", "publisher": "Example Exchange",
                            "available_at": "2020-01-01T00:00:00Z"}),
        envelope("security_symbol", {
            "symbol_id": "symbol_example", "security_id": "SEC_EXAMPLE", "symbol": "EXAMPLE",
            "valid_from": "2020-01-01T00:00:00Z", "source_id": "source_example",
        }),
        envelope("observation", {
            "observation_id": "observation_example", "security_id": "SEC_EXAMPLE",
            "field": "financial.revenue", "value_type": "NUMBER", "value_number": 100.0,
            "unit": "INR_CRORE", "source_id": "source_example",
            "available_at": "2026-05-01T00:00:00Z", "valid_from": "2026-05-01T00:00:00Z",
            "revision_number": 0, "quality_status": "VERIFIED",
        }),
        envelope("universe_membership", {
            "membership_id": "membership_example", "universe_id": "UNIVERSE_EXAMPLE",
            "security_id": "SEC_EXAMPLE", "effective_from": "2020-01-01T00:00:00Z",
            "source_id": "source_example",
        }),
        envelope("corporate_action", {
            "action_id": "action_example", "security_id": "SEC_EXAMPLE",
            "action_type": "DIVIDEND", "source_id": "source_example",
            "available_at": "2026-05-01T00:00:00Z", "cash_amount": 1.0, "currency": "INR",
        }),
    ]


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")


class JsonlImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.database = self.root / "test.sqlite3"
        self.source = self.root / "records.jsonl"

    def tearDown(self):
        self.directory.cleanup()

    def test_malformed_discriminator_and_enum_are_atomic_import_failures(self):
        for invalid, code in (
            (envelope([], {}), "RECORD_TYPE_UNSUPPORTED"),
            (envelope("issuer", {"issuer_id": "bad", "status": []}), "ENUM_INVALID"),
        ):
            with self.subTest(code=code):
                write_jsonl(self.source, [synthetic_envelopes()[0], invalid])
                with PointInTimeStore.open(self.database) as store:
                    with self.assertRaises(ImportFailure) as caught:
                        import_jsonl(store, self.source)
                    self.assertEqual((caught.exception.line, caught.exception.code), (2, code))
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)

    def test_fractional_import_timestamps_do_not_collapse_into_same_second(self):
        for fraction in ("100", "900"):
            with self.subTest(fraction=fraction):
                write_jsonl(self.source, [synthetic_envelopes()[0], envelope("source", {
                    "source_id": "fractional", "publisher": "Exchange",
                    "available_at": f"2026-05-15T12:34:21.{fraction}Z",
                })])
                with PointInTimeStore.open(self.database) as store:
                    with self.assertRaises(ImportFailure) as caught:
                        import_jsonl(store, self.source)
                    self.assertEqual((caught.exception.line, caught.exception.code), (2, "TIMESTAMP_PRECISION_UNSUPPORTED"))
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)

    def test_lossy_fractional_import_timestamps_are_atomic_failures(self):
        for index, timestamp in enumerate((
            "2026-05-15T12:34:21.0000009Z",
            "2026-05-15T12:34:21.0000001Z",
            "2026-05-15T12:34:21+05:30:00.5",
            "2026-05-15T12:34:21+05:30:00.0000009",
        )):
            with self.subTest(timestamp=timestamp):
                write_jsonl(self.source, [synthetic_envelopes()[0], envelope("source", {
                    "source_id": "fractional", "publisher": "Exchange", "available_at": timestamp,
                })])
                with PointInTimeStore.open(self.root / f"fractional-{index}.sqlite3") as store:
                    with self.assertRaises(ImportFailure) as caught:
                        import_jsonl(store, self.source)
                    self.assertEqual((caught.exception.line, caught.exception.code), (2, "TIMESTAMP_PRECISION_UNSUPPORTED"))
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)

    def test_invalid_line_rolls_back_complete_file(self):
        write_jsonl(self.source, [synthetic_envelopes()[0]])
        self.source.write_text(self.source.read_text(encoding="utf-8") + "{invalid json}\n", encoding="utf-8")
        with PointInTimeStore.open(self.database) as store:
            with self.assertRaises(ImportFailure) as caught:
                import_jsonl(store, self.source)
            self.assertEqual((caught.exception.line, caught.exception.code), (2, "JSON_INVALID"))
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)

    def test_nonstandard_json_numbers_are_json_invalid_with_line(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                record = synthetic_envelopes()[4]
                line = json.dumps(record, sort_keys=True).replace("100.0", constant)
                self.source.write_text(json.dumps(synthetic_envelopes()[0], sort_keys=True) + "\n" + line + "\n", encoding="utf-8")
                with PointInTimeStore.open(self.database) as store:
                    with self.assertRaises(ImportFailure) as caught:
                        import_jsonl(store, self.source)
                    self.assertEqual((caught.exception.path, caught.exception.line, caught.exception.code), (str(self.source), 2, "JSON_INVALID"))
                    self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)

    def test_validation_error_rolls_back_complete_file(self):
        records = synthetic_envelopes()
        records[1]["record"]["issuer_id"] = "missing"
        write_jsonl(self.source, records[:2])
        with PointInTimeStore.open(self.database) as store:
            with self.assertRaises(ImportFailure) as caught:
                import_jsonl(store, self.source)
            self.assertEqual((caught.exception.line, caught.exception.code), (2, "ISSUER_MISSING"))
            self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)

    def test_successful_import_is_idempotent(self):
        write_jsonl(self.source, synthetic_envelopes())
        with PointInTimeStore.open(self.database) as store:
            first = import_jsonl(store, self.source)
            second = import_jsonl(store, self.source)
        self.assertEqual(first["inserted"], len(synthetic_envelopes()))
        self.assertEqual(first["unchanged"], 0)
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["unchanged"], len(synthetic_envelopes()))

    def test_blank_line_is_rejected_with_line_number(self):
        self.source.write_text("\n", encoding="utf-8")
        with PointInTimeStore.open(self.database) as store:
            with self.assertRaises(ImportFailure) as caught:
                import_jsonl(store, self.source)
        self.assertEqual((caught.exception.line, caught.exception.code), (1, "BLANK_LINE"))

    def test_file_change_between_passes_rolls_back_before_commit(self):
        write_jsonl(self.source, synthetic_envelopes()[:1])
        original_ingest = PointInTimeStore.ingest
        changed = {"done": False}

        def ingest_and_change(store, record, *, commit=True):
            result = original_ingest(store, record, commit=commit)
            if not changed["done"]:
                changed["done"] = True
                store_path = pathlib.Path(self.source)
                store_path.write_text(
                    store_path.read_text(encoding="utf-8").replace("Example Limited", "Changed Limited"),
                    encoding="utf-8",
                )
            return result

        PointInTimeStore.ingest = ingest_and_change
        try:
            with PointInTimeStore.open(self.database) as store:
                with self.assertRaises(ImportFailure) as caught:
                    import_jsonl(store, self.source)
                self.assertEqual(caught.exception.code, "FILE_CHANGED_DURING_IMPORT")
                self.assertEqual(store.connection.execute("SELECT COUNT(*) FROM issuers").fetchone()[0], 0)
        finally:
            PointInTimeStore.ingest = original_ingest


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.directory.name)
        self.database = self.root / "test.sqlite3"
        self.source = self.root / "records.jsonl"

    def tearDown(self):
        self.directory.cleanup()

    def call(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, json.loads(stdout.getvalue()) if stdout.getvalue() else None, json.loads(stderr.getvalue()) if stderr.getvalue() else None

    def test_init_outputs_json(self):
        code, payload, error = self.call(["init", str(self.database)])
        self.assertEqual((code, payload["schema_version"], error), (0, SCHEMA_VERSION, None))

    def test_ingest_outputs_counts(self):
        write_jsonl(self.source, synthetic_envelopes())
        self.assertEqual(self.call(["init", str(self.database)])[0], 0)
        code, payload, error = self.call(["ingest", str(self.database), str(self.source)])
        self.assertEqual((code, payload["inserted"], error), (0, len(synthetic_envelopes()), None))

    def test_as_of_outputs_observation(self):
        write_jsonl(self.source, synthetic_envelopes())
        self.call(["ingest", str(self.database), str(self.source)])
        code, payload, error = self.call(["as-of", str(self.database), "SEC_EXAMPLE", "financial.revenue", "--cutoff", "2026-06-01T00:00:00Z"])
        self.assertEqual((code, payload["observation_id"], error), (0, "observation_example", None))

    def test_universe_outputs_membership(self):
        write_jsonl(self.source, synthetic_envelopes())
        self.call(["ingest", str(self.database), str(self.source)])
        code, payload, error = self.call(["universe", str(self.database), "UNIVERSE_EXAMPLE", "--cutoff", "2026-06-01T00:00:00Z"])
        self.assertEqual((code, payload[0]["security_id"], error), (0, "SEC_EXAMPLE", None))

    def test_packet_outputs_evidence(self):
        write_jsonl(self.source, synthetic_envelopes())
        self.call(["ingest", str(self.database), str(self.source)])
        code, payload, error = self.call(["packet", str(self.database), "SEC_EXAMPLE", "--cutoff", "2026-06-01T00:00:00Z"])
        self.assertEqual((code, payload["security_id"], error), (0, "SEC_EXAMPLE", None))

    def test_integrity_outputs_valid_report(self):
        self.assertEqual(self.call(["init", str(self.database)])[0], 0)
        code, payload, error = self.call(["integrity", str(self.database)])
        self.assertEqual((code, payload["valid"], error), (0, True, None))

    def test_validation_error_is_structured_json(self):
        code, payload, error = self.call(["as-of", str(self.root / "missing.sqlite3"), "sec", "field", "--cutoff", "not-a-time"])
        self.assertNotEqual(code, 0)
        self.assertIsNone(payload)
        self.assertIn("code", error)

    def test_ingest_nonstandard_json_number_is_structured_import_error(self):
        line = json.dumps(synthetic_envelopes()[4], sort_keys=True).replace("100.0", "NaN")
        self.source.write_text(line + "\n", encoding="utf-8")
        self.assertEqual(self.call(["init", str(self.database)])[0], 0)
        code, payload, error = self.call(["ingest", str(self.database), str(self.source)])
        self.assertEqual((code, payload), (2, None))
        self.assertEqual((error["path"], error["line"], error["code"]), (str(self.source), 1, "JSON_INVALID"))


if __name__ == "__main__":
    unittest.main()
