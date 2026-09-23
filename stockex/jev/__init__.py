"""Optional advisory integration with TypeSafe AI's Jev decision model."""

from .client import (
    API_KEY_ENV, DEFAULT_MODEL, JevClient, JevConfigError, JevError,
    JevRequestError, JevResponseError, validate_questions,
)
from .triage import (
    CONFLICT_QUESTIONS, DEFAULT_CONFIDENCE_FLOOR, EVIDENCE_QUESTIONS,
    QUESTION_BANK_VERSION, triage_packet,
)

__all__ = [
    "API_KEY_ENV", "DEFAULT_MODEL", "JevClient", "JevConfigError", "JevError",
    "JevRequestError", "JevResponseError", "validate_questions",
    "CONFLICT_QUESTIONS", "DEFAULT_CONFIDENCE_FLOOR", "EVIDENCE_QUESTIONS",
    "QUESTION_BANK_VERSION", "triage_packet",
]
