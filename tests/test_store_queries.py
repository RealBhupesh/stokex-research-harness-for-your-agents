import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

from stockex.store.database import PointInTimeStore
from stockex.store.records import StoreValidationError, validate_envelope
from stockex.store.schema import initialize_database


class ObservationQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / "stockex.sqlite3"
        self.store = PointInTimeStore.open(self.path)
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "issuer",
            "record": {"issuer_id": "issuer_example", "legal_name": "Example Limited"},
        }))
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "security",
            "record": {"security_id": "INE000A01001", "issuer_id": "issuer_example"},
        }))
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "security",
            "record": {"security_id": "INE999A01001", "issuer_id": "issuer_example"},
        }))
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "source",
            "record": {"source_id": "src_exchange_1", "publisher": "Example Exchange",
                       "available_at": "2020-01-01T00:00:00Z"},
        }))

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def ingest_observation(
        self,
        observation_id,
        value,
        available_at,
        *,
        revision_of,
        revision_number,
        value_type="NUMBER",
        security_id="INE000A01001",
        field="financial.revenue",
        valid_from=None,
        valid_to=None,
        quality_status="VERIFIED",
    ):
        value_fields = {
            "NUMBER": "value_number",
            "TEXT": "value_text",
            "BOOLEAN": "value_boolean",
            "DATE": "value_date",
            "JSON": "value_json",
        }
        record = {
            "observation_id": observation_id,
            "security_id": security_id,
            "field": field,
            "value_type": value_type,
            value_fields[value_type]: value,
            "source_id": "src_exchange_1",
            "available_at": available_at,
            "valid_from": valid_from or available_at,
            "valid_to": valid_to,
            "revision_of": revision_of,
            "revision_number": revision_number,
            "quality_status": quality_status,
        }
        if value_type == "NUMBER":
            record["unit"] = "INR_CRORE"
        return self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "observation",
            "record": record,
        }))

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
        self.assertEqual(after["source"]["source_id"], "src_exchange_1")

    def test_excludes_future_and_quarantined_records(self):
        self.ingest_observation(
            "future", 100.0, "2027-01-01T00:00:00Z", revision_of=None, revision_number=0
        )
        self.assertIsNone(self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-12-31T23:59:59Z"
        ))
        self.ingest_observation(
            "quarantined", 90.0, "2026-01-01T00:00:00Z", revision_of=None,
            revision_number=0, quality_status="QUARANTINED",
        )
        self.assertIsNone(self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-01-02T00:00:00Z"
        ))

    def test_rejects_broken_revision_chain(self):
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v2", 90.0, "2026-06-12T00:00:00Z",
                revision_of="missing", revision_number=2,
            )
        self.assertEqual(caught.exception.code, "REVISION_PARENT_MISSING")

    def test_rejects_revision_with_different_security_than_parent(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v1", 90.0, "2026-06-12T00:00:00Z", revision_of="obs_v0",
                revision_number=1, security_id="INE999A01001",
            )
        self.assertEqual(caught.exception.code, "REVISION_SECURITY_MISMATCH")

    def test_rejects_revision_with_different_field_than_parent(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v1", 90.0, "2026-06-12T00:00:00Z", revision_of="obs_v0",
                revision_number=1, field="financial.profit",
            )
        self.assertEqual(caught.exception.code, "REVISION_FIELD_MISMATCH")

    def test_rejects_non_sequential_revision_number(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v2", 90.0, "2026-06-12T00:00:00Z", revision_of="obs_v0", revision_number=2
            )
        self.assertEqual(caught.exception.code, "REVISION_NUMBER_INVALID")

    def test_rejects_revision_available_before_parent(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v1", 90.0, "2026-05-15T12:29:59Z", revision_of="obs_v0", revision_number=1
            )
        self.assertEqual(caught.exception.code, "REVISION_AVAILABLE_AT_INVALID")

    def test_revision_closes_only_parent_validity_interval(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0
        )
        self.ingest_observation(
            "obs_v1", 92.0, "2026-06-10T09:00:00Z", revision_of="obs_v0", revision_number=1
        )
        parent = self.store.connection.execute(
            """
            SELECT value_number, source_id, available_at, revision_of, revision_number, valid_to
            FROM observations WHERE observation_id = 'obs_v0'
            """
        ).fetchone()
        self.assertEqual(parent["value_number"], 100.0)
        self.assertEqual(parent["source_id"], "src_exchange_1")
        self.assertEqual(parent["available_at"], "2026-05-15T12:30:00Z")
        self.assertIsNone(parent["revision_of"])
        self.assertEqual(parent["revision_number"], 0)
        self.assertEqual(parent["valid_to"], "2026-06-10T09:00:00Z")

    def test_rejects_revision_start_before_parent_interval(self):
        self.ingest_observation(
            "obs_v0", 100.0, "2026-05-15T12:30:00Z", revision_of=None, revision_number=0,
            valid_from="2026-06-01T00:00:00Z",
        )
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "obs_v1", 90.0, "2026-06-12T00:00:00Z", revision_of="obs_v0", revision_number=1,
                valid_from="2026-05-01T00:00:00Z",
            )
        self.assertEqual(caught.exception.code, "REVISION_INTERVAL_INVALID")

    def test_rejects_naive_query_cutoff(self):
        with self.assertRaises(StoreValidationError) as caught:
            self.store.observation_as_of(
                "INE000A01001", "financial.revenue", "2026-06-01T00:00:00"
            )
        self.assertEqual(caught.exception.code, "TIMESTAMP_NAIVE")

    def test_rejects_fractional_query_cutoffs_without_collapsing_them(self):
        for fraction in ("100", "900"):
            for query in (
                lambda cutoff: self.store.observation_as_of("INE000A01001", "financial.revenue", cutoff),
                lambda cutoff: self.store.universe_as_of("TEST", cutoff),
                lambda cutoff: self.store.evidence_packet("INE000A01001", cutoff),
            ):
                with self.subTest(fraction=fraction, query=query):
                    with self.assertRaises(StoreValidationError) as caught:
                        query(f"2026-06-01T00:00:00.{fraction}Z")
                    self.assertEqual(caught.exception.code, "TIMESTAMP_PRECISION_UNSUPPORTED")

    def test_rejects_lossy_fractional_query_cutoffs(self):
        for cutoff in (
            "2026-05-15T12:34:21.0000009Z",
            "2026-05-15T12:34:21.0000001Z",
            "2026-05-15T12:34:21+05:30:00.5",
            "2026-05-15T12:34:21+05:30:00.0000009",
        ):
            for query_name, query in (
                ("observation", lambda: self.store.observation_as_of("INE000A01001", "financial.revenue", cutoff)),
                ("universe", lambda: self.store.universe_as_of("TEST", cutoff)),
                ("packet", lambda: self.store.evidence_packet("INE000A01001", cutoff)),
            ):
                with self.subTest(cutoff=cutoff, query=query_name):
                    with self.assertRaises(StoreValidationError) as caught:
                        query()
                    self.assertEqual(caught.exception.code, "TIMESTAMP_PRECISION_UNSUPPORTED")


    def test_rejects_caller_supplied_observation_valid_to(self):
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "closed_original", 100.0, "2026-05-15T12:30:00Z",
                revision_of=None, revision_number=0, valid_to="2026-06-01T00:00:00Z",
            )
        self.assertEqual(caught.exception.code, "OBSERVATION_VALID_TO_MANAGED")

    def test_preserves_all_supported_typed_observation_values(self):
        cases = (
            ("NUMBER", 12.5, 12.5, 12.5, None),
            ("TEXT", "reported", "reported", None, "reported"),
            ("BOOLEAN", True, True, None, "true"),
            (
                "DATE", "2026-05-15T18:04:21+05:30", "2026-05-15T12:34:21Z",
                None, "2026-05-15T12:34:21Z",
            ),
            ("JSON", {"z": [2], "a": 1}, {"a": 1, "z": [2]}, None, '{"a":1,"z":[2]}'),
        )
        for value_type, submitted, expected_value, expected_number, expected_text in cases:
            with self.subTest(value_type=value_type):
                field = f"financial.{value_type.lower()}"
                self.ingest_observation(
                    f"obs_{value_type.lower()}", submitted, "2026-05-15T12:30:00Z",
                    revision_of=None, revision_number=0, value_type=value_type, field=field,
                )
                selected = self.store.observation_as_of(
                    "INE000A01001", field, "2026-05-16T00:00:00Z"
                )
                self.assertEqual(selected["value_type"], value_type)
                self.assertEqual(selected["value"], expected_value)
                self.assertEqual(selected["value_number"], expected_number)
                self.assertEqual(selected["value_text"], expected_text)


class StoreFixture(unittest.TestCase):
    """A point-in-time store with one identifiable security and source."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.directory.name) / "stockex.sqlite3"
        self.store = PointInTimeStore.open(
            self.path, clock=lambda: datetime(2026, 6, 2, 3, 4, 5, tzinfo=timezone.utc)
        )
        for record_type, record in (
            ("issuer", {"issuer_id": "issuer_example", "legal_name": "Example Limited"}),
            ("security", {"security_id": "INE000A01001", "issuer_id": "issuer_example"}),
            ("source", {"source_id": "src_exchange_1", "publisher": "Example Exchange",
                        "available_at": "2020-01-01T00:00:00Z"}),
            ("security_symbol", {
                "symbol_id": "symbol1", "security_id": "INE000A01001", "symbol": "EXAMPLE",
                "valid_from": "2020-01-01T00:00:00Z", "source_id": "src_exchange_1",
            }),
        ):
            self.store.ingest(validate_envelope({
                "schema_version": 1, "record_type": record_type, "record": record,
            }))

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def ingest_observation(self, observation_id, field, value, available_at, **overrides):
        record = {
            "observation_id": observation_id,
            "security_id": "INE000A01001",
            "field": field,
            "value_type": "NUMBER",
            "value_number": value,
            "unit": "INR_CRORE",
            "source_id": "src_exchange_1",
            "available_at": available_at,
            "valid_from": available_at,
            "revision_number": 0,
            "quality_status": "VERIFIED",
        }
        record.update(overrides)
        return self.store.ingest(validate_envelope({
            "schema_version": 1, "record_type": "observation", "record": record,
        }))

    def ingest_two_fields_in_reverse_order(self):
        self.ingest_observation("obs_revenue", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.ingest_observation("obs_assets", "financial.assets", 200.0, "2026-05-01T00:00:00Z")

    def ingest_membership(self, membership_id, universe_id, effective_from, effective_to):
        return self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "universe_membership",
            "record": {
                "membership_id": membership_id,
                "universe_id": universe_id,
                "security_id": "INE000A01001",
                "effective_from": effective_from,
                "effective_to": effective_to,
                "source_id": "src_exchange_1",
            },
        }))

    def ingest_corporate_action(self, action_id="action1", available_at="2026-05-20T00:00:00Z"):
        return self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "corporate_action",
            "record": {
                "action_id": action_id,
                "security_id": "INE000A01001",
                "action_type": "DIVIDEND",
                "source_id": "src_exchange_1",
                "available_at": available_at,
                "cash_amount": 5.0,
                "currency": "INR",
            },
        }))

    def corrupt_without_database_checks(self, statements):
        self.store.connection.commit()
        self.store.connection.execute("PRAGMA foreign_keys = OFF")
        self.store.connection.execute("PRAGMA ignore_check_constraints = ON")
        triggers = self.store.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'observations'"
        ).fetchall()
        for trigger in triggers:
            self.store.connection.execute(f'DROP TRIGGER "{trigger["name"]}"')
        try:
            for statement, parameters in statements:
                self.store.connection.execute(statement, parameters)
            self.store.connection.commit()
        finally:
            self.store.connection.execute("PRAGMA ignore_check_constraints = OFF")
            self.store.connection.execute("PRAGMA foreign_keys = ON")
            initialize_database(self.store.connection)


class UniverseQueryTests(StoreFixture):
    def test_excludes_membership_with_future_or_unknown_source_availability(self):
        self.ingest_membership("m1", "TEST", "2025-01-01T00:00:00Z", None)
        for availability in ("2026-06-01T00:00:00Z", None):
            with self.subTest(availability=availability):
                self.store.connection.execute(
                    "UPDATE sources SET available_at = ? WHERE source_id = ?",
                    (availability, "src_exchange_1"),
                )
                self.store.connection.execute("UPDATE security_symbols SET source_id = NULL")
                self.store.connection.commit()
                self.assertEqual(self.store.universe_as_of("TEST", "2026-03-01T00:00:00Z"), [])
        self.store.connection.execute("UPDATE universe_memberships SET source_id = NULL")
        self.assertEqual(len(self.store.universe_as_of("TEST", "2026-03-01T00:00:00Z")), 1)

    def test_excludes_symbols_with_future_or_unknown_source_availability(self):
        self.ingest_membership("m1", "TEST", "2025-01-01T00:00:00Z", None)
        self.store.connection.execute("UPDATE universe_memberships SET source_id = NULL")
        for availability in ("2026-06-01T00:00:00Z", None):
            with self.subTest(availability=availability):
                self.store.connection.execute(
                    "UPDATE sources SET available_at = ? WHERE source_id = ?",
                    (availability, "src_exchange_1"),
                )
                self.store.connection.commit()
                with self.subTest(query="universe"):
                    self.assertEqual(self.store.universe_as_of("TEST", "2026-03-01T00:00:00Z"), [])
                with self.subTest(query="security"):
                    self.assertIsNone(self.store._security_as_of("INE000A01001", "2026-03-01T00:00:00Z")["symbol"])
        self.store.connection.execute("UPDATE security_symbols SET source_id = NULL")
        self.assertEqual(len(self.store.universe_as_of("TEST", "2026-03-01T00:00:00Z")), 1)
        self.assertEqual(self.store._security_as_of("INE000A01001", "2026-03-01T00:00:00Z")["symbol"], "EXAMPLE")

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
    def test_backdated_revision_cannot_rewrite_prior_cutoff(self):
        self.ingest_observation("original", "financial.revenue", 100, "2026-01-01T00:00:00Z")
        with self.assertRaises(StoreValidationError) as caught:
            self.ingest_observation(
                "revision", "financial.revenue", 90, "2026-06-01T00:00:00Z",
                valid_from="2026-02-01T00:00:00Z", revision_of="original", revision_number=1,
            )
        self.assertEqual(caught.exception.code, "REVISION_VALID_FROM_INVALID")
        self.assertEqual(self.store.observation_as_of(
            "INE000A01001", "financial.revenue", "2026-03-01T00:00:00Z"
        )["observation_id"], "original")
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 1)
        self.assertIsNone(self.store.connection.execute("SELECT valid_to FROM observations").fetchone()[0])

    def test_revision_cannot_close_parent_before_source_availability(self):
        for source_id in ("future", "unknown"):
            self.ingest_observation(f"original_{source_id}", "financial.revenue", 100, "2026-01-01T00:00:00Z")
        for source_id, availability in (("future", "2026-06-01T00:00:00Z"), ("unknown", None)):
            with self.subTest(source_id=source_id):
                self.store.ingest(validate_envelope({"schema_version": 1, "record_type": "source", "record": {
                    "source_id": source_id, "publisher": "Exchange", "available_at": availability,
                }}))
                with self.assertRaises(StoreValidationError) as caught:
                    self.ingest_observation(
                        source_id, "financial.revenue", 90, "2026-02-01T00:00:00Z",
                        source_id=source_id, revision_of=f"original_{source_id}", revision_number=1,
                    )
                self.assertEqual(caught.exception.code, "REVISION_VALID_FROM_INVALID")
                self.assertIsNone(self.store.connection.execute(
                    "SELECT valid_to FROM observations WHERE observation_id = ?", (f"original_{source_id}",)
                ).fetchone()[0])
                self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2)

    def test_integrity_detects_backdated_revision_and_unavailable_source(self):
        self.ingest_observation("original", "financial.revenue", 100, "2026-01-01T00:00:00Z")
        self.ingest_observation(
            "revision", "financial.revenue", 90, "2026-02-01T00:00:00Z",
            revision_of="original", revision_number=1,
        )
        for revision_availability, source_availability in (
            ("2026-06-01T00:00:00Z", "2020-01-01T00:00:00Z"),
            ("2026-02-01T00:00:00Z", "2026-06-01T00:00:00Z"),
            ("2026-02-01T00:00:00Z", None),
        ):
            with self.subTest(revision=revision_availability, source=source_availability):
                self.corrupt_without_database_checks((
                    ("UPDATE observations SET available_at = ? WHERE observation_id = ?", (revision_availability, "revision")),
                    ("UPDATE sources SET available_at = ? WHERE source_id = ?", (source_availability, "src_exchange_1")),
                ))
                self.assertIn({"code": "REVISION_CHAIN_INVALID", "observation_id": "revision"}, self.store.integrity_report()["errors"])

    def test_future_published_source_without_availability_is_not_strict_evidence(self):
        self.store.ingest(validate_envelope({"schema_version": 1, "record_type": "source", "record": {
            "source_id": "unknown", "publisher": "Exchange", "published_at": "2027-01-01T00:00:00Z",
        }}))
        for observation_id, value in (("a", 100), ("b", 90)):
            self.ingest_observation(observation_id, "financial.revenue", value, "2026-01-01T00:00:00Z", source_id="unknown")
        for action_id, source_id in (("sourced", "unknown"), ("unsourced", None)):
            self.store.ingest(validate_envelope({"schema_version": 1, "record_type": "corporate_action", "record": {
                "action_id": action_id, "security_id": "INE000A01001", "source_id": source_id,
                "available_at": "2026-01-01T00:00:00Z",
            }}))
        packet = self.store.evidence_packet("INE000A01001", "2026-03-01T00:00:00Z")
        for key in ("observations", "conflicts", "sources"):
            with self.subTest(key=key):
                self.assertEqual(packet[key], [])
        self.assertEqual([row["action_id"] for row in packet["corporate_actions"]], ["unsourced"])
        self.assertIsNone(self.store.observation_as_of("INE000A01001", "financial.revenue", "2026-03-01T00:00:00Z"))

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

    def test_filters_fields_and_reports_requested_gaps(self):
        self.ingest_two_fields_in_reverse_order()
        packet = self.store.evidence_packet(
            "INE000A01001", "2026-06-01T00:00:00Z",
            fields=["financial.revenue", "financial.missing"],
        )
        self.assertEqual([row["field"] for row in packet["observations"]], ["financial.revenue"])
        self.assertEqual(packet["gaps"], ["financial.missing"])

    def test_excludes_post_cutoff_actions_and_deduplicates_sources(self):
        self.ingest_two_fields_in_reverse_order()
        self.ingest_corporate_action("future_action", "2026-06-02T00:00:00Z")
        self.ingest_corporate_action("past_action", "2026-05-20T00:00:00Z")
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual([row["action_id"] for row in packet["corporate_actions"]], ["past_action"])
        self.assertEqual([row["source_id"] for row in packet["sources"]], ["src_exchange_1"])

    def test_excludes_observations_and_actions_with_sources_unavailable_at_cutoff(self):
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "source",
            "record": {
                "source_id": "src_future",
                "publisher": "Future Source",
                "available_at": "2026-06-02T00:00:00Z",
            },
        }))
        self.ingest_observation(
            "obs_future_source", "financial.revenue", 100.0, "2026-05-20T00:00:00Z",
            source_id="src_future",
        )
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "corporate_action",
            "record": {
                "action_id": "action_future_source",
                "security_id": "INE000A01001",
                "action_type": "DIVIDEND",
                "source_id": "src_future",
                "available_at": "2026-05-20T00:00:00Z",
                "cash_amount": 5.0,
                "currency": "INR",
            },
        }))

        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual(packet["observations"], [])
        self.assertEqual(packet["corporate_actions"], [])
        self.assertEqual(packet["sources"], [])
        self.assertEqual(packet["gaps"], ["financial.revenue"])

    def test_generated_at_uses_injected_clock_without_mutating_store(self):
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual(packet["generated_at"], "2026-06-02T03:04:05Z")
        self.assertEqual(self.store.connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 0)

    def test_packet_uses_the_documented_top_level_and_integrity_contract(self):
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual(packet["schema_version"], 1)
        self.assertEqual(packet["security_id"], "INE000A01001")
        self.assertNotIn("security", packet)
        self.assertEqual(packet["integrity"], {
            "strict_point_in_time": True,
            "quarantined_records_excluded": 0,
        })

    def test_reports_equal_time_competing_records_and_quarantined_exclusion(self):
        self.ingest_observation("obs_a", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.ingest_observation("obs_b", "financial.revenue", 101.0, "2026-05-01T00:00:00Z")
        self.ingest_observation(
            "obs_quarantined", "financial.profit", 25.0, "2026-05-01T00:00:00Z",
            quality_status="QUARANTINED",
        )
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual(packet["conflicts"][0]["field"], "financial.revenue")
        self.assertEqual(packet["integrity"]["quarantined_records_excluded"], 1)

    def test_packet_sources_include_provenance_for_conflicting_records(self):
        self.store.ingest(validate_envelope({
            "schema_version": 1,
            "record_type": "source",
            "record": {"source_id": "src_second", "publisher": "Second Source",
                       "available_at": "2020-01-01T00:00:00Z"},
        }))
        self.ingest_observation("obs_a", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.ingest_observation(
            "obs_b", "financial.revenue", 101.0, "2026-05-01T00:00:00Z", source_id="src_second"
        )
        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        self.assertEqual([row["source_id"] for row in packet["sources"]], ["src_exchange_1", "src_second"])

    def test_conflicts_group_same_validity_timestamp_across_availability_times(self):
        self.ingest_observation(
            "obs_a", "financial.revenue", 100.0, "2026-05-01T00:00:00Z",
            valid_from="2026-04-01T00:00:00Z",
        )
        self.ingest_observation(
            "obs_b", "financial.revenue", 101.0, "2026-05-02T00:00:00Z",
            valid_from="2026-04-01T00:00:00Z",
        )

        packet = self.store.evidence_packet("INE000A01001", "2026-06-01T00:00:00Z")
        conflict = packet["conflicts"][0]
        self.assertEqual([row["observation_id"] for row in conflict["observations"]], ["obs_a", "obs_b"])
        self.assertEqual(
            [row["available_at"] for row in conflict["observations"]],
            ["2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z"],
        )
        self.assertEqual(conflict["available_at"], [
            "2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z",
        ])

        report = self.store.integrity_report()
        self.assertFalse(report["valid"])
        error = report["errors"][0]
        self.assertEqual(error["observation_ids"], ["obs_a", "obs_b"])
        self.assertEqual(error["available_at"], [
            "2026-05-01T00:00:00Z", "2026-05-02T00:00:00Z",
        ])

    def test_integrity_distinguishes_same_value_warnings_from_value_errors(self):
        self.ingest_observation("obs_a", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.ingest_observation("obs_b", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        report = self.store.integrity_report()
        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"][0]["code"], "EQUAL_TIME_CONFLICT")

        self.ingest_observation("obs_c", "financial.revenue", 101.0, "2026-05-01T00:00:00Z")
        report = self.store.integrity_report()
        self.assertFalse(report["valid"])
        self.assertIn("EQUAL_TIME_CONFLICT", [error["code"] for error in report["errors"]])

    def test_integrity_report_is_clean_for_valid_store(self):
        report = self.store.integrity_report()
        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])

    def test_integrity_detects_foreign_key_interval_revision_and_conflict_corruption(self):
        self.ingest_observation("obs_v0", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.corrupt_without_database_checks((
            ("UPDATE observations SET source_id = ? WHERE observation_id = ?", ("missing_source", "obs_v0")),
            ("UPDATE security_symbols SET valid_to = ? WHERE symbol_id = ?", ("2019-01-01T00:00:00Z", "symbol1")),
            ("UPDATE observations SET revision_of = ?, revision_number = ? WHERE observation_id = ?", ("missing_parent", 2, "obs_v0")),
        ))
        report = self.store.integrity_report()
        codes = [problem["code"] for problem in report["errors"]]
        self.assertIn("FOREIGN_KEY_VIOLATION", codes)
        self.assertIn("INVALID_INTERVAL", codes)
        self.assertIn("REVISION_CHAIN_INVALID", codes)

    def test_integrity_detects_revision_parent_closure_corruption(self):
        self.ingest_observation("obs_v0", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.ingest_observation(
            "obs_v1", "financial.revenue", 92.0, "2026-06-01T00:00:00Z",
            revision_of="obs_v0", revision_number=1,
        )
        self.corrupt_without_database_checks((
            ("UPDATE observations SET valid_to = NULL WHERE observation_id = ?", ("obs_v0",)),
        ))
        report = self.store.integrity_report()
        self.assertIn("REVISION_CHAIN_INVALID", [error["code"] for error in report["errors"]])

    def test_integrity_detects_unsupported_schema_version(self):
        self.store.connection.execute("DELETE FROM schema_migrations WHERE version = 1")
        self.store.connection.execute("UPDATE schema_migrations SET version = 1 WHERE version = 2")
        self.store.connection.commit()
        report = self.store.integrity_report()
        self.assertFalse(report["valid"])
        self.assertIn("SCHEMA_VERSION_INVALID", [error["code"] for error in report["errors"]])

    def test_integrity_detects_noncanonical_comparison_timestamp_corruption(self):
        self.ingest_observation("obs_v0", "financial.revenue", 100.0, "2026-05-01T00:00:00Z")
        self.corrupt_without_database_checks((
            ("UPDATE observations SET available_at = ? WHERE observation_id = ?", ("not-a-timestamp", "obs_v0")),
        ))
        report = self.store.integrity_report()
        self.assertIn("TIMESTAMP_INVALID", [error["code"] for error in report["errors"]])


if __name__ == "__main__":
    unittest.main()
