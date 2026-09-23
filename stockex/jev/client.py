"""Minimal stdlib client for TypeSafe AI's Jev System One decision endpoint."""

import json
import math
import os
from typing import Callable
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
QUESTION_TYPES = {"noul", "choice", "score"}
MAX_OPTIONS = 255
_RETRY_STATUSES = {429, 500, 502, 503, 504}

Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class JevError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class JevConfigError(JevError):
    pass


class JevRequestError(JevError):
    pass


class JevResponseError(JevError):
    pass


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _score_payload(spec: dict) -> dict:
    # Score levels are sent in ``criteria`` like choice options, ordered lowest
    # to highest. Confirm the field name against docs.typesafe.ai/api before
    # relying on live score answers.
    return {"type": "score", "instructions": spec["instructions"], "criteria": dict(spec["criteria"])}


def validate_questions(questions: dict) -> dict:
    """Return the wire payload for a question map, or raise JevRequestError."""
    if not isinstance(questions, dict) or not questions:
        raise JevRequestError("JEV_QUESTIONS_INVALID", "At least one question is required")
    payload = {}
    for question_id, spec in questions.items():
        path = f"questions.{question_id}"
        if not isinstance(question_id, str) or not question_id or not isinstance(spec, dict):
            raise JevRequestError("JEV_QUESTIONS_INVALID", f"{path} must be a named object")
        kind = spec.get("type")
        if kind not in QUESTION_TYPES:
            raise JevRequestError("JEV_QUESTIONS_INVALID", f"{path}.type must be one of {sorted(QUESTION_TYPES)}")
        instructions = spec.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise JevRequestError("JEV_QUESTIONS_INVALID", f"{path}.instructions is required")
        if kind == "noul":
            payload[question_id] = {"type": "noul", "instructions": instructions}
            continue
        criteria = spec.get("criteria")
        if (
            not isinstance(criteria, dict)
            or not 2 <= len(criteria) <= MAX_OPTIONS
            or not all(isinstance(key, str) and key and isinstance(value, str) and value.strip()
                       for key, value in criteria.items())
        ):
            raise JevRequestError(
                "JEV_QUESTIONS_INVALID", f"{path}.criteria needs 2-{MAX_OPTIONS} described options"
            )
        if kind == "choice":
            payload[question_id] = {"type": "choice", "instructions": instructions, "criteria": dict(criteria)}
        else:
            payload[question_id] = _score_payload(spec)
    return payload


def _probability(value: object) -> bool:
    return (
        isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0.0 <= value <= 1.0
    )


def _validate_answer(question_id: str, spec: dict, answer: object) -> dict:
    path = f"answers.{question_id}"
    if not isinstance(answer, dict) or answer.get("type") != spec["type"]:
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path} is missing or has the wrong type")
    if spec["type"] == "noul":
        if not _probability(answer.get("noul")):
            raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.noul must be a probability")
        return answer
    options = set(spec["criteria"])
    selected = answer.get(spec["type"])
    if selected not in options:
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.{spec['type']} must be a requested option")
    probabilities = answer.get("probabilities")
    if probabilities is not None and (
        not isinstance(probabilities, dict)
        or not set(probabilities) <= options
        or not all(_probability(value) for value in probabilities.values())
    ):
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.probabilities is malformed")
    if "confidence" in answer and not _probability(answer["confidence"]):
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.confidence must be a probability")
    return answer


class JevClient:
    """Evaluate a state against typed questions and return validated answers."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: Transport | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        if not self.api_key:
            raise JevConfigError("JEV_CONFIG_MISSING", f"Set {API_KEY_ENV} to call Jev")
        self.model, self.base_url, self.timeout = model, base_url, timeout
        self._transport = transport or _urllib_transport

    def evaluate(self, state: object, questions: dict) -> dict:
        payload = validate_questions(questions)
        body = json.dumps(
            {"model": self.model, "state": state, "questions": payload},
            sort_keys=True, ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        status, raw = self._send(headers, body)
        if status != 200:
            raise JevRequestError("JEV_HTTP_ERROR", f"Jev returned HTTP {status}: {raw[:200]!r}")
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise JevResponseError("JEV_RESPONSE_INVALID", f"Response is not JSON: {error}") from error
        answers = response.get("answers") if isinstance(response, dict) else None
        if not isinstance(answers, dict):
            raise JevResponseError("JEV_RESPONSE_INVALID", "Response has no answers object")
        return {
            "model": response.get("model") if isinstance(response.get("model"), str) else self.model,
            "answers": {
                question_id: _validate_answer(question_id, spec, answers.get(question_id))
                for question_id, spec in payload.items()
            },
            "usage": response.get("usage") if isinstance(response.get("usage"), dict) else {},
        }

    def _send(self, headers: dict, body: bytes) -> tuple[int, bytes]:
        for attempt in range(2):
            try:
                status, raw = self._transport(self.base_url, headers, body, self.timeout)
            except OSError as error:
                if attempt:
                    raise JevRequestError("JEV_HTTP_ERROR", f"Jev request failed: {error}") from error
                continue
            if status not in _RETRY_STATUSES or attempt:
                return status, raw
        raise AssertionError("unreachable")
