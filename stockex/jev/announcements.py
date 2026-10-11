"""Jev classification of exchange announcements the keyword rules could not place.

Keyword rules classify announcements at import. Subjects such as "Updates" or
"Press Release" stay ``OTHER``; Jev reads the subject and details and picks a
category, with a confidence floor below which the row stays ``OTHER``.
"""

from .client import JevError


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


def classify_with_jev(connection, client, *, min_confidence: float = 0.6, limit: int | None = None) -> dict:
    """Reclassify keyword ``OTHER`` announcements with Jev; returns counts."""
    rows = connection.execute(
        "SELECT symbol, broadcast_at, subject, details FROM announcements "
        "WHERE category = 'OTHER' AND category_source = 'KEYWORD' ORDER BY broadcast_at"
        + ("" if limit is None else f" LIMIT {int(limit)}")
    ).fetchall()
    counts = {"examined": 0, "reclassified": 0, "kept_other": 0, "errors": 0}
    for symbol, broadcast_at, subject, details in rows:
        counts["examined"] += 1
        try:
            result = client.evaluate({"subject": subject, "details": (details or "")[:2000]}, ANNOUNCEMENT_QUESTIONS)
        except JevError:
            counts["errors"] += 1
            continue
        answer = result["answers"]["category"]
        confidence = answer.get("confidence") or (answer.get("probabilities") or {}).get(answer["choice"], 0)
        if answer["choice"] == "OTHER" or confidence < min_confidence:
            category, source = "OTHER", "JEV_LOW_CONFIDENCE" if answer["choice"] != "OTHER" else "JEV"
            counts["kept_other"] += 1
        else:
            category, source = answer["choice"], "JEV"
            counts["reclassified"] += 1
        connection.execute(
            "UPDATE announcements SET category = ?, category_source = ? "
            "WHERE symbol = ? AND broadcast_at = ? AND subject = ?",
            (category, source, symbol, broadcast_at, subject),
        )
    connection.commit()
    return counts
