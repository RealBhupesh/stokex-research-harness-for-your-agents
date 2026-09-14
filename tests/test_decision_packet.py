import copy
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_packet import validate_packet


def valid_packet():
    return {
        "metadata": {
            "issuer": "Example Limited",
            "symbol": "EXAMPLE",
            "exchange": "NSE",
            "research_cutoff": "2026-09-13T15:30:00+05:30",
        },
        "mandate": {
            "mode": "LONG_TERM_COMPOUNDING",
            "horizon": "5 years",
            "personalized_sizing": False,
        },
        "sources": [{
            "id": "S1",
            "publisher": "NSE",
            "url": "https://www.nseindia.com/example",
            "source_class": "EXCHANGE",
            "published_at": "2026-09-12T18:00:00+05:30",
            "available_at": "2026-09-12T18:00:00+05:30",
        }],
        "gates": {
            "MANDATE_READY": True,
            "EVIDENCE_COMPLETE": True,
            "RISK_ACCEPTABLE": True,
            "IC_CLEARED": True,
        },
        "risks": {"hard_stops": []},
        "contradictions": [],
        "decision": {
            "research_status": "RESEARCH_CANDIDATE",
            "ic_action": "APPROVE_FOR_CONSIDERATION",
        },
    }


class DecisionPacketValidationTests(unittest.TestCase):
    def test_accepts_consistent_research_packet(self):
        result = validate_packet(valid_packet())
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["gate_summary"]["all_required_passed"])

    def test_rejects_future_dated_evidence(self):
        packet = valid_packet()
        packet["sources"][0]["available_at"] = "2026-09-14T09:00:00+05:30"
        result = validate_packet(packet)
        self.assertIn("EVIDENCE_AFTER_CUTOFF", [error["code"] for error in result["errors"]])

    def test_rejects_missing_source_provenance(self):
        packet = valid_packet()
        del packet["sources"][0]["publisher"]
        result = validate_packet(packet)
        self.assertIn("SOURCE_PROVENANCE_MISSING", [error["code"] for error in result["errors"]])

    def test_approval_cannot_override_failed_gate(self):
        packet = valid_packet()
        packet["gates"]["RISK_ACCEPTABLE"] = False
        result = validate_packet(packet)
        self.assertIn("APPROVAL_WITH_FAILED_GATE", [error["code"] for error in result["errors"]])

    def test_personalized_sizing_requires_portfolio_inputs(self):
        packet = valid_packet()
        packet["mandate"]["personalized_sizing"] = True
        packet["position_size"] = {"rupees": 50_000}
        result = validate_packet(packet)
        self.assertIn("SIZING_INPUTS_MISSING", [error["code"] for error in result["errors"]])

    def test_unresolved_hard_stop_blocks_approval(self):
        packet = valid_packet()
        packet["risks"]["hard_stops"] = [{"id": "R1", "status": "OPEN", "reason": "Auditor resigned"}]
        result = validate_packet(packet)
        self.assertIn("APPROVAL_WITH_HARD_STOP", [error["code"] for error in result["errors"]])

    def test_input_is_not_mutated(self):
        packet = valid_packet()
        before = copy.deepcopy(packet)
        validate_packet(packet)
        self.assertEqual(packet, before)

    def test_controlling_contradiction_blocks_approval(self):
        packet = valid_packet()
        packet["contradictions"] = [{"id": "C1", "controlling": True, "status": "OPEN"}]
        result = validate_packet(packet)
        self.assertIn("APPROVAL_WITH_CONTROLLING_CONTRADICTION", [error["code"] for error in result["errors"]])

    def test_material_legal_or_credit_issue_blocks_approval(self):
        packet = valid_packet()
        packet["legal_credit"] = {
            "issues": [{"id": "L1", "severity": "MATERIAL", "status": "OPEN", "source_ids": ["S1"]}]
        }
        result = validate_packet(packet)
        self.assertIn("APPROVAL_WITH_LEGAL_CREDIT_BLOCKER", [error["code"] for error in result["errors"]])

    def test_speculative_approval_requires_capped_loss_and_exit_controls(self):
        packet = valid_packet()
        packet["mandate"]["mode"] = "ASYMMETRIC_SPECULATION"
        packet["decision"]["research_status"] = "SPECULATIVE_RESEARCH_CANDIDATE"
        result = validate_packet(packet)
        self.assertIn("SPECULATION_CONTROLS_MISSING", [error["code"] for error in result["errors"]])

        packet["speculation_controls"] = {
            "max_capital_at_risk": 10_000,
            "total_loss_accepted": True,
            "catalyst": "Dated regulatory decision",
            "pre_event_exit_plan": "Exit if filing contradicts thesis",
            "post_event_exit_plan": "Exit after market reprices the decision",
            "liquidity_passed": True,
        }
        self.assertTrue(validate_packet(packet)["valid"])

    def test_approval_action_must_match_research_status(self):
        packet = valid_packet()
        packet["decision"]["research_status"] = "REJECT"
        result = validate_packet(packet)
        self.assertIn("APPROVAL_STATUS_CONFLICT", [error["code"] for error in result["errors"]])


if __name__ == "__main__":
    unittest.main()
