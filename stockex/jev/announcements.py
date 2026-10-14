"""Jev classification of exchange announcements the keyword rules could not place.

Keyword rules classify announcements at import. Subjects such as "Updates" or
"Press Release" stay ``OTHER``; Jev reads the subject and details and picks a
category, with a confidence floor below which the row stays ``OTHER``.
"""

from datetime import datetime, timezone
import hashlib
import math

from .client import JevError, JevResponseError, _validate_answer
from ..operations import atomic_transaction
from ..store.records import canonical_json, normalize_timestamp


ANNOUNCEMENT_QUESTION_BANK_VERSION = "2"


ANNOUNCEMENT_QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "Which category best describes this Indian listed company's exchange announcement?",
        "criteria": {
            "RESULTS": "Quarterly or annual financial results",
            "ORDER_WIN": "New order, contract or letter of award",
            "BONUS_SPLIT": "Bonus issue or stock split",
            "BUYBACK": "Share buyback",
            "DIVIDEND": "Dividend declaration or record date",
            "FUND_RAISE": "QIP, preferential issue, rights issue or other fund raising",
            "PROMOTER_TRADE": "Promoter or insider buying, selling or pledge change",
            "CREDIT_RATING": "Credit rating action",
            "M_AND_A": "Acquisition, merger, demerger or scheme of arrangement",
            "LITIGATION": "Litigation, regulatory order or penalty",
            "MANAGEMENT_CHANGE": "Appointment or resignation of directors or key managers",
            "BOARD_MEETING": "Board meeting notice without a decision",
            "OTHER": "Routine compliance or anything else",
        },
    },
    "material": {
        "type": "noul",
        "instructions": "Could this announcement change the company's earnings outlook, risk or share demand?",
    },
}


def announcement_state(subject, details):
    """The exact bounded state sent to Jev, shared with provenance queries."""
    return {"subject": subject, "details": (details or "")[:2000]}


def announcement_hash(subject, details):
    return hashlib.sha256(canonical_json(announcement_state(subject, details)).encode("utf-8")).hexdigest()


def classify_with_jev(connection, client, *, min_confidence: float = 0.6,
                      limit: int | None = None, clock=None) -> dict:
    """Append validated model annotations; never rewrite exchange evidence.

    The model, question bank, exact state and confidence policy form the cache
    identity. A repeated classification preserves its first knowledge timestamp.
    """
    if isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float)) \
            or not math.isfinite(min_confidence) or not 0 < min_confidence <= 1:
        raise ValueError("min_confidence must be finite and in (0, 1]")
    min_confidence = float(min_confidence)
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("limit must be a positive integer")
    model = getattr(client, "model", None)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Announcement classifier requires an explicit requested model")
    rows = connection.execute(
        "SELECT symbol, broadcast_at, subject, details FROM announcements "
        "WHERE (category = 'OTHER' AND category_source = 'KEYWORD') "
        "OR category_source IN ('JEV', 'JEV_LOW_CONFIDENCE') ORDER BY broadcast_at, symbol, subject"
    ).fetchall()
    counts = {"examined": 0, "reclassified": 0, "kept_other": 0, "errors": 0}
    pending = []
    for symbol, broadcast_at, subject, details in rows:
        sha = announcement_hash(subject, details)
        identity = {"symbol": symbol, "broadcast_at": broadcast_at, "subject": subject,
                    "input_sha256": sha, "question_bank_version": ANNOUNCEMENT_QUESTION_BANK_VERSION,
                    "model_requested": model, "confidence_floor": min_confidence}
        classification_id = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        if connection.execute("SELECT 1 FROM announcement_classifications WHERE classification_id=?",
                              (classification_id,)).fetchone():
            continue
        if limit is not None and counts["examined"] >= limit:
            break
        counts["examined"] += 1
        try:
            result = client.evaluate(announcement_state(subject, details), ANNOUNCEMENT_QUESTIONS)
            if not isinstance(result, dict) or not isinstance(result.get("answers"), dict) \
                    or not isinstance(result.get("model"), str) or not result["model"].strip():
                raise JevResponseError("JEV_RESPONSE_INVALID", "Classification response requires model and answers")
            answers = {key: _validate_answer(key, spec, result["answers"].get(key))
                       for key, spec in ANNOUNCEMENT_QUESTIONS.items()}
            validated = {"model": result["model"], "answers": answers}
            answer = answers["category"]
            confidence = answer["confidence"]
            category = answer["choice"]
            applied = category if confidence >= min_confidence else "OTHER"
            now = (clock or (lambda: datetime.now(timezone.utc)))()
            judged_at = normalize_timestamp(now.isoformat(timespec="seconds"), "judged_at")
            if judged_at < broadcast_at:
                raise ValueError("Classification cannot be known before the announcement broadcast")
            response_json = canonical_json(validated)
        except JevError:
            counts["errors"] += 1
            continue
        counts["kept_other" if applied == "OTHER" else "reclassified"] += 1
        pending.append((classification_id, symbol, broadcast_at, subject, sha,
                        ANNOUNCEMENT_QUESTION_BANK_VERSION, model, result["model"], judged_at,
                        confidence, min_confidence, category, applied, response_json))
    with atomic_transaction(connection):
        for row in pending:
            existing = connection.execute(
                "SELECT model_returned, category, applied_category, response_json "
                "FROM announcement_classifications WHERE classification_id=?", (row[0],)
            ).fetchone()
            if existing is not None:
                if tuple(existing) != (row[7], row[11], row[12], row[13]):
                    raise JevResponseError("JEV_CLASSIFICATION_CONFLICT", "Conflicting immutable announcement classification")
                continue
            connection.execute("INSERT INTO announcement_classifications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row)
    return counts
