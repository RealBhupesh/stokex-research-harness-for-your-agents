import unittest

from stockex.store.records import (
    CorporateActionRecord, IssuerRecord, ObservationRecord, SecurityRecord,
    SecuritySymbolRecord, SourceRecord, UniverseMembershipRecord,
    StoreValidationError, canonical_json, normalize_timestamp, validate_envelope,
)


class StoreRecordTests(unittest.TestCase):
    def test_rejects_nonzero_fractional_timestamp_precision(self):
        for fraction in ("100", "900"):
            with self.subTest(fraction=fraction):
                with self.assertRaises(StoreValidationError) as caught:
                    normalize_timestamp(f"2026-05-15T12:34:21.{fraction}Z", "available_at")
                self.assertEqual(caught.exception.code, "TIMESTAMP_PRECISION_UNSUPPORTED")
                self.assertEqual(caught.exception.path, "available_at")

    def test_zero_fractional_seconds_normalize_to_whole_seconds(self):
        for timestamp in (
            "2026-05-15T12:34:21.000Z",
            "2026-05-15T12:34:21.000000000Z",
            "2026-05-15T12:34:21,000000000Z",
            "2026-05-15T18:04:21+05:30:00",
            "2026-05-15T18:04:21.000000000+05:30:00.000000000",
            "2026-05-15T18:04:21,000000000+05:30:00,000000000",
            "2026-05-15T18:04:51+05:30:30",
        ):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(normalize_timestamp(timestamp, "available_at"), "2026-05-15T12:34:21Z")

    def test_rejects_fractional_text_that_datetime_would_lose(self):
        for timestamp in (
            "2026-05-15T12:34:21.0000009Z",
            "2026-05-15T12:34:21.0000001Z",
            "2026-05-15T12:34:21,0000009Z",
            "2026-05-15T12:34:21+05:30:00.5",
            "2026-05-15T12:34:21-05:30:00.5",
            "2026-05-15T12:34:21+05:30:00,5",
            "2026-05-15T12:34:21+05:30:00.0000009",
            "2026-05-15T12:34:21+00:00:00.5",
        ):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(StoreValidationError) as caught:
                    normalize_timestamp(timestamp, "available_at")
                self.assertEqual(caught.exception.code, "TIMESTAMP_PRECISION_UNSUPPORTED")
                self.assertEqual(caught.exception.path, "available_at")

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
            "record_type": "observation", "schema_version": 1,
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

    def test_accepts_observation_and_normalizes_metadata(self):
        record = validate_envelope({"record_type": "observation", "schema_version": 1, "record": {
            "observation_id": "obs1", "security_id": "sec1", "field": "financial.revenue",
            "value_type": "NUMBER", "value_number": 100, "unit": "INR_CRORE", "source_id": "src1",
            "available_at": "2026-05-15T18:04:21+05:30", "valid_from": "2026-05-15T18:04:21+05:30",
            "revision_number": 0, "quality_status": "VERIFIED", "metadata": {"z": 2, "a": 1},
        }})
        self.assertIsInstance(record, ObservationRecord)
        self.assertEqual(record.available_at, "2026-05-15T12:34:21Z")
        self.assertEqual(record.metadata_json, '{"a":1,"z":2}')
        self.assertIn('"record_type":"observation"', record.canonical_json)

    def test_accepts_each_non_observation_record_type(self):
        cases = [
            ("issuer", {"issuer_id": "iss1"}, IssuerRecord),
            ("security", {"security_id": "sec1", "issuer_id": "iss1"}, SecurityRecord),
            ("security_symbol", {"symbol_id": "sym1", "security_id": "sec1", "symbol": "EX"}, SecuritySymbolRecord),
            ("source", {"source_id": "src1", "publisher": "Publisher"}, SourceRecord),
            ("universe_membership", {"membership_id": "mem1", "universe_id": "u1", "security_id": "sec1"}, UniverseMembershipRecord),
            ("corporate_action", {"action_id": "act1", "security_id": "sec1"}, CorporateActionRecord),
        ]
        for record_type, payload, expected_type in cases:
            with self.subTest(record_type=record_type):
                self.assertIsInstance(validate_envelope({"record_type": record_type, "schema_version": 1, "record": payload}), expected_type)

    def test_rejects_invalid_issuer_status(self):
        with self.assertRaises(StoreValidationError) as caught:
            validate_envelope({"record_type": "issuer", "schema_version": 1, "record": {"issuer_id": "iss1", "status": "INVALID"}})
        self.assertEqual(caught.exception.code, "ENUM_INVALID")
