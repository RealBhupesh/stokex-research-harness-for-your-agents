"""Minimal stdlib client for TypeSafe AI's Jev System One decision endpoint."""

import json
import math
import os
import time
from typing import Callable
import urllib.error
import urllib.request
from urllib.parse import urlsplit


DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
API_KEY_ENV = "TYPESAFE_API_KEY"
QUESTION_TYPES = {"noul", "choice", "score"}
MAX_OPTIONS = 255
MAX_SCORE_LEVELS = 10
_RETRY_STATUSES = {429, 500, 502, 503, 504, 529}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a bearer credential to a redirected endpoint.
        return None


def _bounded_read(response):
    raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise JevResponseError("JEV_RESPONSE_TOO_LARGE", "Jev response exceeded the size limit")
    return raw


def _urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        opener = urllib.request.build_opener(_NoRedirect())
        with opener.open(request, timeout=timeout) as response:
            return response.status, _bounded_read(response)
    except urllib.error.HTTPError as error:
        with error:
            return error.code, _bounded_read(error)


def _score_payload(spec: dict) -> dict:
    # Research rubrics use ordered labels; the provider requires an ordered array.
    return {"type": "score", "instructions": spec["instructions"], "criteria": list(spec["criteria"].values())}


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
            or not 2 <= len(criteria) <= (MAX_SCORE_LEVELS if kind == "score" else MAX_OPTIONS)
            or not all(isinstance(key, str) and key and isinstance(value, str) and value.strip()
                       for key, value in criteria.items())
        ):
            raise JevRequestError(
                "JEV_QUESTIONS_INVALID", f"{path}.criteria needs 2-{MAX_SCORE_LEVELS if kind == 'score' else MAX_OPTIONS} described options"
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
    """Validate the wire contract and add an explicit, auditable score adapter.

    ``score`` remains the numeric expected level. ``level`` is the uniquely
    most probable rubric label (None on ties), never a rounded expected value.
    ``level_probabilities`` maps the distribution to the research rubric labels.
    Contract: https://docs.typesafe.ai/api (verified 2026-10-14).
    """
    path = f"answers.{question_id}"
    if not isinstance(answer, dict) or answer.get("type") != spec["type"]:
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path} is missing or has the wrong type")
    if spec["type"] == "noul":
        if not _probability(answer.get("noul")):
            raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.noul must be a probability")
        return dict(answer)
    labels = list(spec["criteria"])
    options = set(labels) if spec["type"] == "choice" else {str(i) for i in range(len(labels))}
    probabilities = answer.get("probabilities")
    if (
        not isinstance(probabilities, dict)
        or set(probabilities) != options
        or not all(_probability(value) for value in probabilities.values())
        or not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-6)
    ):
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.probabilities must cover every option and sum to 1")
    if not _probability(answer.get("confidence")):
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.confidence must be a probability")
    if spec["type"] == "choice":
        selected = answer.get("choice")
        if not isinstance(selected, str) or selected not in options:
            raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.choice must be a requested option")
        if probabilities[selected] < max(probabilities.values()):
            raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.choice must be a highest-probability option")
        return dict(answer)
    legend = {str(i): spec["criteria"][label] for i, label in enumerate(labels)}
    if answer.get("legend") != legend:
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.legend must match the requested ordered levels")
    score = answer.get("score")
    expected = sum(int(index) * probability for index, probability in probabilities.items())
    if (not isinstance(score, (int, float)) or isinstance(score, bool)
            or not math.isfinite(score) or not 0 <= score <= len(labels) - 1
            or not math.isclose(score, expected, rel_tol=0, abs_tol=1e-6)):
        raise JevResponseError("JEV_RESPONSE_INVALID", f"{path}.score must equal the probability-weighted level")
    maximum = max(probabilities.values())
    modes = [index for index, probability in probabilities.items() if probability == maximum]
    return {
        **answer,
        "level": labels[int(modes[0])] if len(modes) == 1 else None,
        "level_probabilities": {label: probabilities[str(i)] for i, label in enumerate(labels)},
    }


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
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
        if self.api_key is None or self.api_key == "":
            raise JevConfigError("JEV_CONFIG_MISSING", f"Set {API_KEY_ENV} to call Jev")
        if not isinstance(self.api_key, str) or any(not 33 <= ord(char) <= 126 for char in self.api_key):
            raise JevConfigError("JEV_CONFIG_INVALID", "Jev API key must be a non-empty ASCII token without whitespace")
        try:
            if not isinstance(base_url, str) or any(not 33 <= ord(char) <= 126 for char in base_url):
                raise ValueError("invalid endpoint characters")
            endpoint = urlsplit(base_url)
            valid_endpoint = (endpoint.scheme == "https" and bool(endpoint.hostname)
                              and endpoint.username is None and endpoint.password is None)
            # Force validation of malformed or out-of-range port declarations.
            endpoint.port
        except (ValueError, TypeError):
            valid_endpoint = False
        if not valid_endpoint:
            raise JevConfigError("JEV_CONFIG_INVALID", "Jev endpoint must be HTTPS without embedded credentials")
        try:
            valid_timeout = (not isinstance(timeout, bool) and isinstance(timeout, (int, float))
                             and math.isfinite(timeout) and timeout > 0)
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise JevConfigError("JEV_CONFIG_INVALID", "Jev timeout must be finite and positive")
        self.model, self.base_url, self.timeout = model, base_url, timeout
        self._transport = transport or _urllib_transport
        self._sleeper = sleeper

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
            raise JevRequestError("JEV_HTTP_ERROR", f"Jev returned HTTP {status}")
        try:
            response = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise JevResponseError("JEV_RESPONSE_INVALID", "Jev response is not valid JSON") from None
        answers = response.get("answers") if isinstance(response, dict) else None
        if not isinstance(answers, dict):
            raise JevResponseError("JEV_RESPONSE_INVALID", "Response has no answers object")
        return {
            "model": response.get("model") if isinstance(response.get("model"), str) else self.model,
            "answers": {
                question_id: _validate_answer(question_id, spec, answers.get(question_id))
                for question_id, spec in questions.items()
            },
            "usage": response.get("usage") if isinstance(response.get("usage"), dict) else {},
        }

    def _send(self, headers: dict, body: bytes) -> tuple[int, bytes]:
        for attempt in range(2):
            if attempt:
                self._sleeper(0.25)
            try:
                status, raw = self._transport(self.base_url, headers, body, self.timeout)
            except OSError:
                if attempt:
                    raise JevRequestError("JEV_HTTP_ERROR", "Jev request failed after retry") from None
                continue
            except JevError:
                raise
            except Exception:
                # urllib and injected transports may include Authorization values
                # in header/encoding errors. Never expose their text or traceback.
                raise JevRequestError("JEV_HTTP_ERROR", "Jev transport failed") from None
            if status not in _RETRY_STATUSES or attempt:
                return status, raw
        raise AssertionError("unreachable")
