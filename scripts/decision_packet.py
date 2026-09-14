"""Validate STOCKEX research packet consistency without making an investment decision."""

import argparse
from datetime import datetime
import json


APPROVAL_ACTIONS = {"APPROVE_FOR_CONSIDERATION", "APPROVE_WITH_CONDITIONS"}
REQUIRED_APPROVAL_GATES = {
    "MANDATE_READY",
    "EVIDENCE_COMPLETE",
    "RISK_ACCEPTABLE",
    "IC_CLEARED",
}


def _error(errors, code, path, message):
    errors.append({"code": code, "path": path, "message": message})


def _timestamp(value, path, errors):
    if not isinstance(value, str):
        _error(errors, "TIMESTAMP_MISSING", path, "A timezone-aware ISO-8601 timestamp is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _error(errors, "TIMESTAMP_INVALID", path, "Timestamp is not valid ISO-8601")
        return None
    if parsed.tzinfo is None:
        _error(errors, "TIMESTAMP_TIMEZONE_MISSING", path, "Timestamp must include a timezone")
        return None
    return parsed


def validate_packet(packet):
    """Return deterministic structural and gate errors for a research decision packet."""
    errors = []
    warnings = []
    if not isinstance(packet, dict):
        return {
            "valid": False,
            "errors": [{"code": "PACKET_NOT_OBJECT", "path": "$", "message": "Packet must be a JSON object"}],
            "warnings": [],
            "gate_summary": {"required": sorted(REQUIRED_APPROVAL_GATES), "failed": [], "missing": [], "all_required_passed": False},
        }

    metadata = packet.get("metadata") if isinstance(packet.get("metadata"), dict) else {}
    cutoff = _timestamp(metadata.get("research_cutoff"), "metadata.research_cutoff", errors)

    sources = packet.get("sources")
    if not isinstance(sources, list) or not sources:
        _error(errors, "SOURCE_LEDGER_MISSING", "sources", "At least one sourced record is required")
        sources = []
    provenance_fields = ("id", "publisher", "url", "source_class", "published_at", "available_at")
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, dict):
            _error(errors, "SOURCE_INVALID", path, "Source must be an object")
            continue
        missing = [field for field in provenance_fields if not source.get(field)]
        if missing:
            _error(errors, "SOURCE_PROVENANCE_MISSING", path, f"Missing fields: {', '.join(missing)}")
        published = _timestamp(source.get("published_at"), f"{path}.published_at", errors)
        available = _timestamp(source.get("available_at"), f"{path}.available_at", errors)
        if cutoff and available and available > cutoff:
            _error(errors, "EVIDENCE_AFTER_CUTOFF", f"{path}.available_at", "Evidence was unavailable at the research cutoff")
        if published and available and available < published:
            _error(errors, "AVAILABILITY_BEFORE_PUBLICATION", path, "available_at cannot precede published_at")

    gates = packet.get("gates") if isinstance(packet.get("gates"), dict) else {}
    missing_gates = sorted(REQUIRED_APPROVAL_GATES - set(gates))
    failed_gates = sorted(name for name in REQUIRED_APPROVAL_GATES if gates.get(name) is False)
    invalid_gates = sorted(name for name, value in gates.items() if type(value) is not bool)
    for gate in invalid_gates:
        _error(errors, "GATE_VALUE_INVALID", f"gates.{gate}", "Gate value must be true or false")

    decision = packet.get("decision") if isinstance(packet.get("decision"), dict) else {}
    action = decision.get("ic_action")
    approving = action in APPROVAL_ACTIONS
    research_status = decision.get("research_status")
    if approving and (missing_gates or failed_gates or invalid_gates):
        _error(errors, "APPROVAL_WITH_FAILED_GATE", "decision.ic_action", "Approval requires every mandatory gate to be present and true")
    if approving and research_status not in {"RESEARCH_CANDIDATE", "SPECULATIVE_RESEARCH_CANDIDATE"}:
        _error(errors, "APPROVAL_STATUS_CONFLICT", "decision", "Approval requires a compatible research-candidate status")

    risks = packet.get("risks") if isinstance(packet.get("risks"), dict) else {}
    hard_stops = risks.get("hard_stops") if isinstance(risks.get("hard_stops"), list) else []
    open_hard_stops = [risk for risk in hard_stops if isinstance(risk, dict) and risk.get("status") != "RESOLVED"]
    if approving and open_hard_stops:
        _error(errors, "APPROVAL_WITH_HARD_STOP", "risks.hard_stops", "Open hard-stop risks prohibit approval")

    contradictions = packet.get("contradictions") if isinstance(packet.get("contradictions"), list) else []
    controlling_conflicts = [
        conflict for conflict in contradictions
        if isinstance(conflict, dict) and conflict.get("controlling") is True and conflict.get("status") != "RESOLVED"
    ]
    if approving and controlling_conflicts:
        _error(
            errors,
            "APPROVAL_WITH_CONTROLLING_CONTRADICTION",
            "contradictions",
            "Unresolved controlling contradictions prohibit approval",
        )

    legal_credit = packet.get("legal_credit") if isinstance(packet.get("legal_credit"), dict) else {}
    legal_issues = legal_credit.get("issues") if isinstance(legal_credit.get("issues"), list) else []
    legal_blockers = [
        issue for issue in legal_issues
        if isinstance(issue, dict)
        and issue.get("severity") in {"MATERIAL", "BLOCKER"}
        and issue.get("status") != "RESOLVED"
    ]
    if approving and legal_blockers:
        _error(
            errors,
            "APPROVAL_WITH_LEGAL_CREDIT_BLOCKER",
            "legal_credit.issues",
            "Open material legal or credit issues prohibit approval",
        )

    mandate = packet.get("mandate") if isinstance(packet.get("mandate"), dict) else {}
    if mandate.get("personalized_sizing") is True:
        portfolio = packet.get("portfolio_inputs") if isinstance(packet.get("portfolio_inputs"), dict) else {}
        required_inputs = ("portfolio_value", "holdings", "max_loss_fraction", "liquidity_limit")
        if any(name not in portfolio for name in required_inputs):
            _error(errors, "SIZING_INPUTS_MISSING", "portfolio_inputs", "Personalized sizing requires portfolio value, holdings, loss limit and liquidity limit")

    if approving and mandate.get("mode") == "ASYMMETRIC_SPECULATION":
        controls = packet.get("speculation_controls") if isinstance(packet.get("speculation_controls"), dict) else {}
        required_controls = (
            "max_capital_at_risk",
            "total_loss_accepted",
            "catalyst",
            "pre_event_exit_plan",
            "post_event_exit_plan",
            "liquidity_passed",
        )
        missing_controls = [name for name in required_controls if name not in controls]
        invalid_controls = (
            not isinstance(controls.get("max_capital_at_risk"), (int, float))
            or isinstance(controls.get("max_capital_at_risk"), bool)
            or controls.get("max_capital_at_risk", 0) <= 0
            or controls.get("total_loss_accepted") is not True
            or controls.get("liquidity_passed") is not True
            or any(not isinstance(controls.get(name), str) or not controls[name].strip()
                   for name in ("catalyst", "pre_event_exit_plan", "post_event_exit_plan"))
        )
        if missing_controls or invalid_controls:
            _error(
                errors,
                "SPECULATION_CONTROLS_MISSING",
                "speculation_controls",
                "Speculative approval requires capped capital, accepted total-loss risk, a dated catalyst, two-sided exit plans and passed liquidity",
            )

    if not sources:
        warnings.append({"code": "NO_EVIDENCE_TO_REVIEW", "message": "No evidence records were available for point-in-time checks"})
    all_required_passed = not missing_gates and not failed_gates and not invalid_gates
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "gate_summary": {
            "required": sorted(REQUIRED_APPROVAL_GATES),
            "failed": failed_gates,
            "missing": missing_gates,
            "all_required_passed": all_required_passed,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet_json", help="Path to a STOCKEX decision packet JSON file")
    args = parser.parse_args()
    with open(args.packet_json, encoding="utf-8") as handle:
        packet = json.load(handle)
    result = validate_packet(packet)
    print(json.dumps(result, indent=2, allow_nan=False))
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
