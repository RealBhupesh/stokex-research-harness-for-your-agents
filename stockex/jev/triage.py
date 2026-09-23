"""Advisory Jev triage over a point-in-time evidence packet.

The report is a review queue. It never changes the packet, stored evidence,
gates or research status.
"""

from datetime import datetime, timezone
import hashlib

from ..store.records import canonical_json
from .client import JevError


REPORT_SCHEMA_VERSION = 1
QUESTION_BANK_VERSION = "1"
DEFAULT_CONFIDENCE_FLOOR = 0.7

SOURCE_CLASSES = {
    "primary_filing": "Statutory filing by the issuer: annual report, audited results, offer document",
    "exchange_disclosure": "Disclosure made to NSE or BSE under listing obligations",
    "regulator": "Order, circular or statement from SEBI, RBI, MCA, a court or another regulator",
    "company_communication": "Press release, investor presentation, earnings call or interview by management",
    "sell_side": "Broker, analyst or rating-agency research",
    "news": "Media reporting by a third party",
    "social": "Social media, forum or messaging post",
    "other": "Anything that fits none of the classes above",
}
CLAIM_TYPES = {
    "verified_fact": "A reported figure or event stated as fact by the primary originator",
    "management_claim": "A statement, target or explanation by management that is not independently verified",
    "analyst_opinion": "An estimate, rating or interpretation by an analyst or journalist",
    "rumour": "An unattributed or unverifiable assertion",
}
MATERIALITY_LEVELS = {
    "immaterial": "Would not change any forecast, valuation or risk judgment",
    "minor": "Refines a detail but does not change a conclusion",
    "material": "Could change a forecast, valuation, risk or catalyst judgment",
    "controlling": "Could by itself decide whether the research case passes or fails",
}

EVIDENCE_QUESTIONS = {
    "source_class": {
        "type": "choice",
        "instructions": "Which class of origin best describes this source for Indian listed-equity research?",
        "criteria": SOURCE_CLASSES,
    },
    "claim_type": {
        "type": "choice",
        "instructions": "What kind of statement is the main content of this source?",
        "criteria": CLAIM_TYPES,
    },
    "materiality": {
        "type": "score",
        "instructions": "How material is this source to an equity research decision on the security?",
        "criteria": MATERIALITY_LEVELS,
    },
    "forward_looking": {
        "type": "noul",
        "instructions": "Is the main content forward-looking (guidance, targets, projections) rather than historical?",
    },
    "restatement_or_amendment": {
        "type": "noul",
        "instructions": "Does this source restate, amend, correct or withdraw earlier reported information?",
    },
}
CONFLICT_QUESTIONS = {
    "contradicts": {
        "type": "noul",
        "instructions": (
            "These observations of the same field and validity time disagree. Is the disagreement "
            "substantive, rather than explained by units, consolidated versus standalone basis, "
            "rounding or a restatement?"
        ),
    },
}

_SOURCE_STATE_FIELDS = ("source_id", "publisher", "source_class", "uri", "published_at", "available_at")
_OBSERVATION_STATE_FIELDS = (
    "observation_id", "field", "value", "unit", "period_start", "period_end",
    "source_id", "available_at", "quality_status",
)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_class(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _certainty(answer: dict) -> float | None:
    """Confidence when Jev returns it, otherwise the probability of the selected option."""
    if "confidence" in answer:
        return answer["confidence"]
    selected = answer.get(answer["type"])
    probabilities = answer.get("probabilities") or {}
    return probabilities.get(selected)


def _selected_probability(answer: dict) -> float | None:
    return (answer.get("probabilities") or {}).get(answer.get(answer["type"]))


def _source_flags(source: dict, answers: dict, floor: float) -> list[dict]:
    flags = []
    for question_id in ("source_class", "claim_type", "materiality"):
        certainty = _certainty(answers[question_id])
        if certainty is None or certainty < floor:
            flags.append({"code": "LOW_CONFIDENCE", "question": question_id, "certainty": certainty})
    low = {flag["question"] for flag in flags}

    declared = _normalized_class(source.get("source_class"))
    predicted = answers["source_class"]["choice"]
    if (
        "source_class" not in low
        and declared in SOURCE_CLASSES
        and declared != predicted
    ):
        flags.append({
            "code": "SOURCE_CLASS_MISMATCH",
            "declared": declared,
            "predicted": predicted,
            "probability": _selected_probability(answers["source_class"]),
        })

    if (
        not {"claim_type", "materiality"} & low
        and answers["materiality"]["score"] in {"material", "controlling"}
        and answers["claim_type"]["choice"] != "verified_fact"
    ):
        flags.append({
            "code": "CLAIM_NOT_FACT",
            "claim_type": answers["claim_type"]["choice"],
            "materiality": answers["materiality"]["score"],
        })

    if answers["restatement_or_amendment"]["noul"] >= floor:
        flags.append({"code": "POSSIBLE_RESTATEMENT", "probability": answers["restatement_or_amendment"]["noul"]})
    return flags


def triage_packet(
    packet: dict,
    excerpts: dict[str, str],
    client,
    *,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    clock=None,
) -> dict:
    """Ask Jev the fixed question bank about each packet source and conflict."""
    if not 0.0 < confidence_floor <= 1.0:
        raise ValueError("confidence_floor must be in (0, 1]")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    sources_report, conflicts_report, errors, models = [], [], [], set()

    packet_source_ids = {source["source_id"] for source in packet.get("sources", [])}
    ignored = sorted(set(excerpts) - packet_source_ids)

    for source in packet.get("sources", []):
        source_id = source["source_id"]
        state = {
            "security_id": packet.get("security_id"),
            "research_cutoff": packet.get("cutoff"),
            "source": {key: source.get(key) for key in _SOURCE_STATE_FIELDS},
            "excerpt": excerpts.get(source_id),
        }
        entry = {
            "source_id": source_id,
            "declared_source_class": source.get("source_class"),
            "has_excerpt": source_id in excerpts,
            "input_sha256": _sha256(state),
        }
        try:
            result = client.evaluate(state, EVIDENCE_QUESTIONS)
        except JevError as error:
            errors.append({"target": f"source:{source_id}", "code": error.code, "message": error.message})
            continue
        models.add(result["model"])
        entry["answers"] = result["answers"]
        entry["flags"] = _source_flags(source, result["answers"], confidence_floor)
        if not entry["has_excerpt"]:
            entry["flags"].append({"code": "METADATA_ONLY"})
        sources_report.append(entry)

    for conflict in packet.get("conflicts", []):
        target = f"conflict:{conflict['field']}@{conflict['valid_from']}"
        state = {
            "security_id": conflict.get("security_id"),
            "field": conflict["field"],
            "valid_from": conflict["valid_from"],
            "observations": [
                {key: observation.get(key) for key in _OBSERVATION_STATE_FIELDS}
                for observation in conflict["observations"]
            ],
        }
        entry = {
            "field": conflict["field"],
            "valid_from": conflict["valid_from"],
            "observation_ids": [observation["observation_id"] for observation in conflict["observations"]],
            "input_sha256": _sha256(state),
        }
        try:
            result = client.evaluate(state, CONFLICT_QUESTIONS)
        except JevError as error:
            errors.append({"target": target, "code": error.code, "message": error.message})
            continue
        models.add(result["model"])
        probability = result["answers"]["contradicts"]["noul"]
        entry["answers"] = result["answers"]
        # Every store conflict stays in the review queue; Jev only ranks it.
        if probability >= confidence_floor:
            flag = {"code": "SUBSTANTIVE_CONFLICT", "probability": probability}
        elif probability <= 1.0 - confidence_floor:
            flag = {"code": "LIKELY_NON_SUBSTANTIVE", "probability": probability}
        else:
            flag = {"code": "LOW_CONFIDENCE", "question": "contradicts", "certainty": probability}
        entry["flags"] = [flag]
        conflicts_report.append(entry)

    review_queue = [
        {"target": f"source:{entry['source_id']}", "flags": [flag["code"] for flag in entry["flags"]]}
        for entry in sources_report
        if any(flag["code"] != "METADATA_ONLY" for flag in entry["flags"])
    ] + [
        {"target": f"conflict:{entry['field']}@{entry['valid_from']}", "flags": [flag["code"] for flag in entry["flags"]]}
        for entry in conflicts_report
        if entry["flags"]
    ] + [
        {"target": error["target"], "flags": ["JEV_UNAVAILABLE"]} for error in errors
    ]

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "advisory_only": True,
        "security_id": packet.get("security_id"),
        "cutoff": packet.get("cutoff"),
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "question_bank_version": QUESTION_BANK_VERSION,
        "confidence_floor": confidence_floor,
        "jev_models": sorted(models),
        "sources": sources_report,
        "conflicts": conflicts_report,
        "review_queue": review_queue,
        "ignored_excerpts": ignored,
        "errors": errors,
    }
