"""Hash-bound evidence and supplied specialist synthesis; no generated analyst claims.

API: ``build_evidence_packet(metadata, mandate, sources, observations,
controlling_evidence=[], decision_context={})`` snapshots JSON and adds SHA-256.
Sources require id/source_id, publisher, url/uri, source_class, published_at and
available_at. Observations require id/observation_id, source_id, field, non-null
value, available_at and quality_status=VERIFIED; validity bounds are honored.
Metadata and mandate follow schema/decision-packet.schema.json. Decision context
holds hash-bound portfolio_inputs, speculation_controls and/or trade_plan.

``synthesize_research(packet, reports, skeptical_review)`` returns valid,
approved_for_consideration, decision, errors, required_roles, evidence_digest and
assurance. See tests/fixtures/research-synthesis.json for a synthetic contract
example, not actual company research. No current source or analyst data is fetched.

The gate checks reproducible record consistency. It cannot authenticate the human
or model behind a reviewer ID, establish source truth, or certify investment merit.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from typing import Any

from scripts.decision_packet import validate_packet

REQUIRED_ROLES = ("fundamentals", "valuation", "market", "risk", "legal_credit")
CONTRACT_VERSION = "stockex.research.v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def build_evidence_packet(metadata: dict, mandate: dict, sources: list[dict],
                          observations: list[dict], *, controlling_evidence: list[dict] | None = None,
                          decision_context: dict | None = None) -> dict:
    """Snapshot caller data and bind every value to a reproducible SHA-256 digest.

    JSON serialization makes the snapshot detached from caller-owned mutable data.
    Any later change invalidates its digest. Invalid evidence can be snapshotted for
    triage, but cannot pass synthesis. Source and observation IDs from the PIT store
    are accepted as aliases for ``id``.
    """
    normalized_sources = []
    for original in sources:
        source = deepcopy(original)
        if isinstance(source, dict):
            source.setdefault("id", source.get("source_id"))
            source.setdefault("url", source.get("uri"))
        normalized_sources.append(source)
    normalized_observations = []
    for original in observations:
        observation = deepcopy(original)
        if isinstance(observation, dict):
            observation.setdefault("id", observation.get("observation_id"))
        normalized_observations.append(observation)
    content = {"contract_version": CONTRACT_VERSION, "metadata": metadata, "mandate": mandate,
               "sources": normalized_sources, "observations": normalized_observations,
               "controlling_evidence": controlling_evidence if controlling_evidence is not None else [],
               "decision_context": decision_context if decision_context is not None else {}}
    snapshot = json.loads(_canonical(content))
    return {**snapshot, "evidence_digest": _digest(snapshot)}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def synthesize_research(evidence_packet: dict, reports: list[dict], skeptical_review: dict) -> dict:
    """Fail closed unless cited specialist records and independent review agree.

    No external calls occur and no specialist research is fabricated. Reports and
    skeptical review must be supplied by the caller. Concerns require a new review
    iteration rather than a self-declared ``resolved`` or gate boolean.
    """
    errors: list[dict] = []
    def error(code: str, path: str, message: str) -> None:
        errors.append({"code": code, "path": path, "message": message})
    def result() -> dict:
        passed = not errors
        return {"contract_version": CONTRACT_VERSION,
                "evidence_digest": evidence_packet.get("evidence_digest") if isinstance(evidence_packet, dict) else None,
                "valid": passed, "approved_for_consideration": passed,
                "decision": {"research_status": ("SPECULATIVE_RESEARCH_CANDIDATE" if isinstance(evidence_packet.get("mandate"), dict) and evidence_packet["mandate"].get("mode") == "ASYMMETRIC_SPECULATION" else "RESEARCH_CANDIDATE") if passed else "INSUFFICIENT_DATA",
                             "ic_action": "APPROVE_FOR_CONSIDERATION" if passed else "RETURN_FOR_WORK"},
                "errors": errors, "required_roles": list(REQUIRED_ROLES),
                "assurance": "Supplied-record consistency only; reviewer identity, source truth and investment merit are not certified."}
    if not isinstance(evidence_packet, dict):
        error("EVIDENCE_INVALID", "$", "Evidence must be an object")
        return result()
    content = {key: value for key, value in evidence_packet.items() if key != "evidence_digest"}
    try:
        digest_valid = _text(evidence_packet.get("evidence_digest")) and _digest(content) == evidence_packet["evidence_digest"]
    except (TypeError, ValueError, OverflowError):
        digest_valid = False
    if not digest_valid:
        error("EVIDENCE_DIGEST_MISMATCH", "evidence_digest", "Evidence changed or has no valid digest")
    if evidence_packet.get("contract_version") != CONTRACT_VERSION:
        error("CONTRACT_VERSION_INVALID", "contract_version", "Unsupported evidence contract")
    # Reuse the source/mandate validator in a nonapproving state; gates are derived
    # here and never imported from evidence or supplied specialist booleans.
    base = {key: evidence_packet.get(key) for key in ("metadata", "mandate", "sources")}
    base.update(gates={}, risks={"hard_stops": []}, contradictions=[],
                decision={"research_status": "INSUFFICIENT_DATA", "ic_action": "RETURN_FOR_WORK"})
    context = evidence_packet.get("decision_context")
    if not isinstance(context, dict):
        error("DECISION_CONTEXT_INVALID", "decision_context", "Decision context must be an object")
        context = {}
    for key in ("portfolio_inputs", "speculation_controls", "trade_plan"):
        if key in context:
            base[key] = context[key]
    errors.extend(validate_packet(base)["errors"])
    cutoff = _time((base["metadata"] or {}).get("research_cutoff")) if isinstance(base["metadata"], dict) else None
    sources = evidence_packet.get("sources")
    source_ids = {source["id"] for source in sources if isinstance(source, dict) and _text(source.get("id"))} if isinstance(sources, list) else set()
    observations = evidence_packet.get("observations")
    observation_sources: dict[str, str] = {}
    observation_values: dict[tuple, str] = {}
    source_times = {source["id"]: _time(source.get("available_at")) for source in sources
                    if isinstance(source, dict) and _text(source.get("id"))} if isinstance(sources, list) else {}
    if not isinstance(observations, list) or not observations:
        error("OBSERVATIONS_MISSING", "observations", "At least one cited observation is required")
        observations = []
    for index, observation in enumerate(observations):
        path = f"observations[{index}]"
        if not isinstance(observation, dict):
            error("OBSERVATION_INVALID", path, "Observation must be an object")
            continue
        oid, sid = observation.get("id"), observation.get("source_id")
        if not _text(oid) or oid in observation_sources:
            error("OBSERVATION_ID_INVALID", path, "Observation IDs must be unique nonempty strings")
            continue
        if not _text(sid) or sid not in source_ids:
            error("OBSERVATION_SOURCE_UNKNOWN", path, "Observation must reference a packet source")
        observation_sources[oid] = sid
        available = _time(observation.get("available_at"))
        if not available or not cutoff or available > cutoff:
            error("OBSERVATION_UNAVAILABLE", path, "Observation must be available at the research cutoff")
        if not _text(observation.get("field")) or "value" not in observation or observation["value"] is None:
            error("OBSERVATION_VALUE_MISSING", path, "Observation field and non-null value required")
        if observation.get("quality_status") != "VERIFIED":
            error("OBSERVATION_QUALITY_FAILED", path, "Only verified observations can support approval")
        source_available = source_times.get(sid) if _text(sid) else None
        if available and source_available and available < source_available:
            error("OBSERVATION_PRECEDES_SOURCE", path, "Observation cannot be available before its source")
        for bound in ("valid_from", "valid_to"):
            if observation.get(bound) is not None:
                valid = _time(observation[bound])
                if not valid or not cutoff or (bound == "valid_from" and valid > cutoff) or (bound == "valid_to" and valid <= cutoff):
                    error("OBSERVATION_NOT_VALID_AT_CUTOFF", path, "Observation validity bounds exclude the cutoff or are malformed")
        # Equal-time differing claims cannot be silently combined into consensus.
        try:
            key = tuple(_canonical(observation.get(field)) for field in ("security_id", "field", "period_end", "valid_from", "available_at", "revision_number"))
            value = _canonical(observation.get("value"))
            if key in observation_values and observation_values[key] != value:
                error("OBSERVATION_CONFLICT", path, "Equal-time observations disagree; reconcile controlling evidence first")
            observation_values[key] = value
        except (ValueError, TypeError, OverflowError):
            error("OBSERVATION_INVALID", path, "Observation must contain finite JSON data")

    def citations(record: dict, path: str) -> None:
        srefs, orefs = record.get("source_ids"), record.get("observation_ids")
        if not isinstance(srefs, list) or not srefs or any(not _text(ref) or ref not in source_ids for ref in srefs):
            error("SOURCE_CITATION_INVALID", path, "Nonempty known source citations required")
        if not isinstance(orefs, list) or not orefs or any(not _text(ref) or ref not in observation_sources for ref in orefs):
            error("OBSERVATION_CITATION_INVALID", path, "Nonempty known observation citations required")
        elif isinstance(srefs, list):
            for ref in orefs:
                if observation_sources[ref] not in srefs:
                    error("CITATION_PROVENANCE_MISMATCH", path, "Cited observation's source must also be cited")

    controls = evidence_packet.get("controlling_evidence")
    if not isinstance(controls, list):
        error("CONTROLLING_EVIDENCE_INVALID", "controlling_evidence", "Controlling evidence must be an array")
    else:
        for index, control in enumerate(controls):
            path = f"controlling_evidence[{index}]"
            if not isinstance(control, dict):
                error("CONTROLLING_EVIDENCE_INVALID", path, "Control must be an object")
                continue
            citations(control, path)
            # A supplied resolution flag is not independent resolution evidence.
            # Open controls are retained in the immutable packet and block this run.
            error("UNRESOLVED_CONTROLLING_EVIDENCE", path,
                  "Controlling evidence requires reconciliation in a new evidence packet before approval")

    if not isinstance(reports, list):
        error("REPORTS_INVALID", "reports", "Specialist reports must be an array")
        reports = []
    roles, reviewers, report_ids, finding_keys = set(), set(), set(), set()
    for index, report in enumerate(reports):
        path = f"reports[{index}]"
        if not isinstance(report, dict):
            error("REPORT_INVALID", path, "Report must be an object")
            continue
        rid, role, reviewer = report.get("id"), report.get("role"), report.get("reviewer_id")
        if not _text(rid) or rid in report_ids:
            error("REPORT_ID_INVALID", path, "Unique report ID required")
        else:
            report_ids.add(rid)
        if not _text(role) or role not in REQUIRED_ROLES or role in roles:
            error("REPORT_ROLE_INVALID", path, "Exactly one report for each required role is required")
        else:
            roles.add(role)
        if not _text(reviewer) or reviewer in reviewers:
            error("REVIEWER_NOT_INDEPENDENT", path, "Distinct specialist reviewer IDs required")
        else:
            reviewers.add(reviewer)
        if report.get("status") != "COMPLETE" or not _text(report.get("conclusion")):
            error("REPORT_INCOMPLETE", path, "Complete status and substantive conclusion required")
        if report.get("evidence_digest") != evidence_packet.get("evidence_digest"):
            error("REPORT_EVIDENCE_MISMATCH", path, "Report must bind to this evidence digest")
        findings = report.get("findings")
        if not isinstance(findings, list) or not findings:
            error("FINDINGS_MISSING", path, "At least one cited finding required per report")
            continue
        for findex, finding in enumerate(findings):
            fpath = f"{path}.findings[{findex}]"
            if not isinstance(finding, dict):
                error("FINDING_INVALID", fpath, "Finding must be an object")
                continue
            fid = finding.get("id")
            if not _text(fid) or not _text(rid) or (rid, fid) in finding_keys:
                error("FINDING_ID_INVALID", fpath, "Unique finding ID required within report")
            else:
                finding_keys.add((rid, fid))
            if finding.get("assessment") != "SUPPORTS":
                error("FINDING_NOT_CLEARED", fpath, "Unknown assessment, concern or blocker prevents approval")
            if not _text(finding.get("rationale")):
                error("FINDING_RATIONALE_MISSING", fpath, "Evidence-based rationale required")
            citations(finding, fpath)
    for missing in sorted(set(REQUIRED_ROLES) - roles):
        error("SPECIALIST_ROLE_MISSING", "reports", f"Missing required specialist: {missing}")

    if not isinstance(skeptical_review, dict):
        error("SKEPTICAL_REVIEW_MISSING", "skeptical_review", "Independent skeptical review required")
        return result()
    skeptic = skeptical_review
    if not _text(skeptic.get("id")) or not _text(skeptic.get("reviewer_id")) or skeptic["reviewer_id"] in reviewers:
        error("SKEPTIC_NOT_INDEPENDENT", "skeptical_review", "Skeptic must have an ID distinct from all specialist reviewers")
    if skeptic.get("status") != "COMPLETE" or skeptic.get("evidence_digest") != evidence_packet.get("evidence_digest"):
        error("SKEPTICAL_REVIEW_INCOMPLETE", "skeptical_review", "Completed review bound to current evidence required")
    reviews = skeptic.get("reviews")
    covered = set()
    if not isinstance(reviews, list) or not reviews:
        error("SKEPTICAL_COVERAGE_MISSING", "skeptical_review.reviews", "Every specialist finding requires cited review")
        reviews = []
    for index, review in enumerate(reviews):
        path = f"skeptical_review.reviews[{index}]"
        if not isinstance(review, dict):
            error("SKEPTICAL_REVIEW_INVALID", path, "Review must be an object")
            continue
        rid, fid = review.get("report_id"), review.get("finding_id")
        if not _text(rid) or not _text(fid) or (rid, fid) not in finding_keys or (rid, fid) in covered:
            error("SKEPTICAL_REFERENCE_INVALID", path, "Unique reference to an existing specialist finding required")
        else:
            covered.add((rid, fid))
        if review.get("verdict") != "ACCEPT" or not _text(review.get("rationale")):
            error("SKEPTICAL_CHALLENGE_UNRESOLVED", path, "Unresolved, rejected or unexplained review prevents approval")
        citations(review, path)
    if covered != finding_keys:
        error("SKEPTICAL_COVERAGE_INCOMPLETE", "skeptical_review.reviews", "Skeptic must review every specialist finding")
    if not errors:
        approval = deepcopy(base)
        approval["gates"] = {name: True for name in ("MANDATE_READY", "EVIDENCE_COMPLETE", "RISK_ACCEPTABLE", "IC_CLEARED")}
        approval["decision"] = {"research_status": "SPECULATIVE_RESEARCH_CANDIDATE" if base["mandate"]["mode"] == "ASYMMETRIC_SPECULATION" else "RESEARCH_CANDIDATE",
                                "ic_action": "APPROVE_FOR_CONSIDERATION"}
        errors.extend(validate_packet(approval)["errors"])
    return result()
