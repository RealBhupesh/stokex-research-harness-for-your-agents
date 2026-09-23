import copy
from datetime import datetime, timezone
import pathlib
import tempfile
import unittest

from stockex.jev.client import JevRequestError, validate_questions
from stockex.jev.triage import CONFLICT_QUESTIONS, EVIDENCE_QUESTIONS, triage_packet
from stockex.store.database import PointInTimeStore
from stockex.store.records import validate_envelope


CUTOFF = "2026-06-01T00:00:00Z"


def envelope(record_type, record):
    return {"schema_version": 1, "record_type": record_type, "record": record}


def records():
    return [
        envelope("issuer", {"issuer_id": "issuer_x", "legal_name": "Example Limited"}),
        envelope("security", {"security_id": "SEC_X", "issuer_id": "issuer_x", "exchange": "NSE"}),
        envelope("source", {"source_id": "filing", "publisher": "NSE", "source_class": "primary_filing",
                            "published_at": "2026-05-01T00:00:00Z", "available_at": "2026-05-01T00:00:00Z"}),
        envelope("source", {"source_id": "blog", "publisher": "Blog", "source_class": "exchange_disclosure",
                            "published_at": "2026-05-02T00:00:00Z", "available_at": "2026-05-02T00:00:00Z"}),
        envelope("source", {"source_id": "late", "publisher": "NSE", "source_class": "primary_filing",
                            "published_at": "2026-07-01T00:00:00Z", "available_at": "2026-07-01T00:00:00Z"}),
        *[
            envelope("observation", {
                "observation_id": f"rev_{source}", "security_id": "SEC_X", "field": "financial.revenue",
                "value_type": "NUMBER", "value_number": value, "unit": "INR_CRORE", "source_id": source,
                "available_at": available, "valid_from": "2026-04-30T00:00:00Z",
                "revision_number": 0, "quality_status": "VERIFIED",
            })
            for source, value, available in (
                ("filing", 100.0, "2026-05-01T00:00:00Z"),
                ("blog", 140.0, "2026-05-02T00:00:00Z"),
                ("late", 90.0, "2026-07-01T00:00:00Z"),
            )
        ],
    ]


def choice(kind, selected, probability, confidence=None):
    answer = {"type": kind, kind: selected, "probabilities": {selected: probability}}
    if confidence is not None:
        answer["confidence"] = confidence
    return answer


def source_answers(source_class="primary_filing", class_p=0.95, claim="verified_fact",
                   materiality="material", restated=0.05, confidence=0.9):
    return {
        "source_class": choice("choice", source_class, class_p, confidence),
        "claim_type": choice("choice", claim, 0.9, confidence),
        "materiality": choice("score", materiality, 0.85, confidence),
        "forward_looking": {"type": "noul", "noul": 0.1},
        "restatement_or_amendment": {"type": "noul", "noul": restated},
    }


class FakeClient:
    def __init__(self, by_source, conflict_p=0.9, fail=()):
        self.by_source, self.conflict_p, self.fail = by_source, conflict_p, set(fail)
        self.calls = []

    def evaluate(self, state, questions):
        self.calls.append((copy.deepcopy(state), questions))
        if questions is CONFLICT_QUESTIONS:
            return {"model": "jev-1.13.0", "answers": {"contradicts": {"type": "noul", "noul": self.conflict_p}}}
        source_id = state["source"]["source_id"]
        if source_id in self.fail:
            raise JevRequestError("JEV_HTTP_ERROR", "Jev returned HTTP 503")
        return {"model": "jev-1.13.0", "answers": self.by_source[source_id]}


def fixed_clock():
    return datetime(2026, 6, 2, tzinfo=timezone.utc)


class JevTriageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        with PointInTimeStore.open(pathlib.Path(self.directory.name) / "t.sqlite3") as store:
            for item in records():
                store.ingest(validate_envelope(item))
            self.packet = store.evidence_packet("SEC_X", CUTOFF)

    def tearDown(self):
        self.directory.cleanup()

    def triage(self, client, excerpts=None, **kwargs):
        return triage_packet(self.packet, excerpts or {}, client, clock=fixed_clock, **kwargs)

    def flags(self, report, source_id):
        entry = next(item for item in report["sources"] if item["source_id"] == source_id)
        return [flag["code"] for flag in entry["flags"]]

    def test_packet_is_point_in_time_and_contains_conflict(self):
        self.assertEqual([s["source_id"] for s in self.packet["sources"]], ["blog", "filing"])
        self.assertEqual(len(self.packet["conflicts"]), 1)

    def test_flags_mismatch_claim_and_substantive_conflict(self):
        client = FakeClient({
            "filing": source_answers(),
            "blog": source_answers(source_class="social", claim="rumour", materiality="controlling"),
        })
        report = self.triage(client, {"filing": "Revenue was Rs 100 crore", "blog": "Revenue will be 140"})
        self.assertTrue(report["advisory_only"])
        self.assertEqual(self.flags(report, "filing"), [])
        self.assertEqual(self.flags(report, "blog"), ["SOURCE_CLASS_MISMATCH", "CLAIM_NOT_FACT"])
        self.assertEqual(report["conflicts"][0]["flags"][0]["code"], "SUBSTANTIVE_CONFLICT")
        self.assertEqual(report["conflicts"][0]["observation_ids"], ["rev_filing", "rev_blog"])
        self.assertEqual(
            [item["target"] for item in report["review_queue"]],
            ["source:blog", "conflict:financial.revenue@2026-04-30T00:00:00Z"],
        )
        self.assertEqual(report["jev_models"], ["jev-1.13.0"])
        self.assertEqual(report["generated_at"], "2026-06-02T00:00:00Z")

    def test_low_confidence_suppresses_dependent_flags(self):
        client = FakeClient({
            "filing": source_answers(),
            "blog": source_answers(source_class="social", claim="rumour", confidence=0.4),
        }, conflict_p=0.5)
        report = self.triage(client, {"filing": "a", "blog": "b"})
        self.assertEqual(self.flags(report, "blog"), ["LOW_CONFIDENCE"] * 3)
        self.assertEqual(report["conflicts"][0]["flags"][0]["code"], "LOW_CONFIDENCE")

    def test_certainty_falls_back_to_selected_probability(self):
        client = FakeClient({
            "filing": source_answers(class_p=0.5, confidence=None),
            "blog": source_answers(source_class="exchange_disclosure", confidence=None),
        }, conflict_p=0.1)
        report = self.triage(client, {"filing": "a", "blog": "b"})
        self.assertEqual(self.flags(report, "filing"), ["LOW_CONFIDENCE"])
        self.assertEqual(self.flags(report, "blog"), [])
        self.assertEqual(report["conflicts"][0]["flags"][0]["code"], "LIKELY_NON_SUBSTANTIVE")

    def test_restatement_and_metadata_only_flags(self):
        client = FakeClient({"filing": source_answers(restated=0.9), "blog": source_answers("exchange_disclosure")})
        report = self.triage(client)
        self.assertEqual(self.flags(report, "filing"), ["POSSIBLE_RESTATEMENT", "METADATA_ONLY"])
        self.assertEqual(self.flags(report, "blog"), ["METADATA_ONLY"])
        self.assertNotIn("source:blog", [item["target"] for item in report["review_queue"]])

    def test_excerpts_outside_cutoff_packet_are_ignored_and_never_sent(self):
        client = FakeClient({"filing": source_answers(), "blog": source_answers("exchange_disclosure")})
        report = self.triage(client, {"filing": "a", "late": "future restatement to 90"})
        self.assertEqual(report["ignored_excerpts"], ["late"])
        sent = " ".join(str(state) for state, _ in client.calls)
        self.assertNotIn("future restatement", sent)
        self.assertNotIn("rev_late", sent)

    def test_jev_failure_is_a_gap_not_a_crash(self):
        client = FakeClient({"filing": source_answers()}, fail={"blog"})
        report = self.triage(client, {"filing": "a"})
        self.assertEqual([item["source_id"] for item in report["sources"]], ["filing"])
        self.assertEqual(report["errors"][0]["target"], "source:blog")
        self.assertIn({"target": "source:blog", "flags": ["JEV_UNAVAILABLE"]}, report["review_queue"])

    def test_input_hash_is_deterministic_and_packet_unchanged(self):
        before = copy.deepcopy(self.packet)
        answers = {"filing": source_answers(), "blog": source_answers("exchange_disclosure")}
        first = self.triage(FakeClient(answers), {"filing": "a"})
        second = self.triage(FakeClient(answers), {"filing": "a"})
        changed = self.triage(FakeClient(answers), {"filing": "b"})
        self.assertEqual(self.packet, before)
        self.assertEqual(first, second)
        self.assertNotEqual(first["sources"][1]["input_sha256"], changed["sources"][1]["input_sha256"])

    def test_questions_are_valid_for_the_client_and_floor_is_checked(self):
        validate_questions(EVIDENCE_QUESTIONS)
        validate_questions(CONFLICT_QUESTIONS)
        with self.assertRaises(ValueError):
            self.triage(FakeClient({}), confidence_floor=0)


if __name__ == "__main__":
    unittest.main()
