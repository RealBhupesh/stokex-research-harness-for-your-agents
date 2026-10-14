"""Validate STOCKEX research packet consistency without making an investment decision."""

import argparse
from datetime import datetime
import json
import math


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


MANDATE_MODES = {"CAPITAL_PRESERVATION", "LONG_TERM_COMPOUNDING", "TACTICAL_SWING", "EVENT_DRIVEN", "ASYMMETRIC_SPECULATION", "AGGRESSIVE_SHORT_TERM"}
RESEARCH_STATUSES = {"RESEARCH_CANDIDATE", "SPECULATIVE_RESEARCH_CANDIDATE", "WATCH", "REJECT", "SCREEN_ONLY", "INSUFFICIENT_DATA"}
IC_ACTIONS = APPROVAL_ACTIONS | {"RETURN_FOR_WORK", "VETO"}


def _positive_number(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _structure_errors(packet):
    """Reject malformed safety containers before evaluating their contents."""
    errors = []
    def bad(path, message):
        _error(errors, "STRUCTURE_INVALID", path, message)
    def text(value):
        return isinstance(value, str) and bool(value.strip())
    for field in ("metadata", "mandate", "gates", "risks", "decision"):
        if not isinstance(packet.get(field), dict):
            bad(field, "Required object is missing or malformed")
    if errors:
        return errors
    metadata, mandate, decision = packet["metadata"], packet["mandate"], packet["decision"]
    for field in ("issuer", "symbol"):
        if not text(metadata.get(field)):
            bad("metadata." + field, "Nonempty string required")
    if metadata.get("exchange") not in ("NSE", "BSE"):
        bad("metadata.exchange", "Exchange must be NSE or BSE")
    if not isinstance(mandate.get("mode"), str) or mandate["mode"] not in MANDATE_MODES:
        bad("mandate.mode", "Unknown mandate mode")
    if not text(mandate.get("horizon")) or type(mandate.get("personalized_sizing")) is not bool:
        bad("mandate", "Horizon and boolean personalized_sizing are required")
    for field, choices in (("research_status", RESEARCH_STATUSES), ("ic_action", IC_ACTIONS)):
        if not isinstance(decision.get(field), str) or decision[field] not in choices:
            bad("decision." + field, "Unknown or missing decision state")
    containers = [("risks.hard_stops", packet["risks"].get("hard_stops"), "risk"),
                  ("contradictions", packet.get("contradictions"), "contradiction")]
    if "legal_credit" in packet:
        legal = packet["legal_credit"]
        containers.append(("legal_credit.issues", legal.get("issues") if isinstance(legal, dict) else None, "legal"))
    for path, items, kind in containers:
        if not isinstance(items, list):
            bad(path, "Safety records must be an array")
            continue
        ids = set()
        for index, item in enumerate(items):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                bad(item_path, "Safety record must be an object")
                continue
            identifier = item.get("id")
            if not text(identifier) or identifier in ids:
                bad(item_path + ".id", "Unique nonempty identifier required")
            else:
                ids.add(identifier)
            if item.get("status") not in ("OPEN", "RESOLVED"):
                bad(item_path + ".status", "Status must be OPEN or RESOLVED")
            if kind == "contradiction" and type(item.get("controlling")) is not bool:
                bad(item_path + ".controlling", "Boolean controlling flag required")
            if kind == "legal" and item.get("severity") not in ("LOW", "MODERATE", "MATERIAL", "BLOCKER"):
                bad(item_path + ".severity", "Known severity required")
    return errors


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

    structural_errors = _structure_errors(packet)
    if structural_errors:
        return {"valid": False, "errors": structural_errors, "warnings": [],
                "gate_summary": {"required": sorted(REQUIRED_APPROVAL_GATES), "failed": [],
                                 "missing": [], "all_required_passed": False}}

    metadata = packet.get("metadata") if isinstance(packet.get("metadata"), dict) else {}
    cutoff = _timestamp(metadata.get("research_cutoff"), "metadata.research_cutoff", errors)

    sources = packet.get("sources")
    if not isinstance(sources, list) or not sources:
        _error(errors, "SOURCE_LEDGER_MISSING", "sources", "At least one sourced record is required")
        sources = []
    provenance_fields = ("id", "publisher", "url", "source_class", "published_at", "available_at")
    source_ids = set()
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, dict):
            _error(errors, "SOURCE_INVALID", path, "Source must be an object")
            continue
        missing = [field for field in provenance_fields
                   if not isinstance(source.get(field), str) or not source[field].strip()]
        identifier = source.get("id")
        if isinstance(identifier, str):
            if identifier in source_ids:
                _error(errors, "DUPLICATE_SOURCE_ID", path + ".id", "Source IDs must be unique")
            source_ids.add(identifier)
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
        if (any(name not in portfolio for name in required_inputs)
                or not _positive_number(portfolio.get("portfolio_value"))
                or not isinstance(portfolio.get("holdings"), list)
                or not _positive_number(portfolio.get("max_loss_fraction"))
                or portfolio.get("max_loss_fraction", 2) > 1
                or not _positive_number(portfolio.get("liquidity_limit"))):
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
            not _positive_number(controls.get("max_capital_at_risk"))
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

    if approving and mandate.get("mode") == "AGGRESSIVE_SHORT_TERM":
        plan = packet.get("trade_plan") if isinstance(packet.get("trade_plan"), dict) else {}

        def positive(name):
            value = plan.get(name)
            return _positive_number(value)

        prices_valid = all(positive(name) for name in ("entry", "stop", "target")) and (
            plan["stop"] < plan["entry"] < plan["target"]
        )
        time_stop = plan.get("time_stop_sessions")
        if not (
            prices_valid
            and isinstance(time_stop, int) and not isinstance(time_stop, bool) and 1 <= time_stop <= 20
            and positive("position_size_rupees")
            and plan.get("liquidity_passed") is True
        ):
            _error(
                errors,
                "TRADE_PLAN_MISSING",
                "trade_plan",
                "Aggressive short-term approval requires entry, stop below entry, target above entry, a 1-20 session time stop, a position size and passed liquidity",
            )

    for path, records in (("risks.hard_stops", hard_stops), ("contradictions", contradictions), ("legal_credit.issues", legal_issues)):
        for index, record in enumerate(records):
            for key in ("source_ids", "resolution_source_ids"):
                if key not in record and not (key == "resolution_source_ids" and record["status"] == "RESOLVED"):
                    continue
                refs = record.get(key)
                if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in source_ids for ref in refs):
                    _error(errors, "SAFETY_EVIDENCE_INVALID", f"{path}[{index}].{key}", "Safety and resolution citations must reference known sources")
    warnings.append({"code": "STRUCTURAL_VALIDATION_ONLY", "message": "Packet consistency and caller-supplied gates do not certify independent diligence; use the supplied-specialist synthesis contract for citation and skeptical-review checks"})
    if not sources:
        warnings.append({"code": "NO_EVIDENCE_TO_REVIEW", "message": "No evidence records were available for point-in-time checks"})
    all_required_passed = not errors and not missing_gates and not failed_gates and not invalid_gates
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
