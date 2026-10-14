import json
import os
import unittest
import io
from unittest import mock

from stockex.jev.client import (
    JevClient, JevConfigError, JevRequestError, JevResponseError, validate_questions,
    MAX_RESPONSE_BYTES, _bounded_read, _NoRedirect,
)


QUESTIONS = {
    "topic": {"type": "choice", "instructions": "Pick one", "criteria": {"billing": "Money", "bug": "Defect"}},
    "urgent": {"type": "noul", "instructions": "Escalate now?"},
    "severity": {"type": "score", "instructions": "How bad?", "criteria": {"low": "Minor", "high": "Severe"}},
}
ANSWERS = {
    "topic": {"type": "choice", "choice": "billing", "probabilities": {"billing": 0.9, "bug": 0.1}, "confidence": 0.9},
    "urgent": {"type": "noul", "noul": 0.82},
    "severity": {"type": "score", "score": 0.8, "legend": {"0": "Minor", "1": "Severe"}, "probabilities": {"0": 0.2, "1": 0.8}, "confidence": 0.75},
}


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, payload = response
        return status, payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")


def ok(answers=ANSWERS):
    return 200, {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 10}}


class JevClientTests(unittest.TestCase):
    def test_transport_bounds_responses_and_refuses_redirects(self):
        with self.assertRaises(JevResponseError):
            _bounded_read(io.BytesIO(b"x" * (MAX_RESPONSE_BYTES + 1)))
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_insecure_endpoint_and_invalid_timeout_are_rejected(self):
        for kwargs in ({"base_url": "http://api.example.com"},
                       {"base_url": "https://user:secret@api.example.com"},
                       {"timeout": float("nan")}, {"timeout": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(JevConfigError):
                JevClient("key", **kwargs)

    def test_http_errors_do_not_echo_provider_secrets(self):
        with self.assertRaises(JevRequestError) as caught:
            JevClient("secret-key", transport=FakeTransport((401, b"secret-key"))).evaluate("s", QUESTIONS)
        self.assertNotIn("secret-key", str(caught.exception))

    def test_retry_waits_and_uses_bounded_attempt_count(self):
        sleeper = mock.Mock()
        transport = FakeTransport((429, {}), ok())
        JevClient("key", transport=transport, sleeper=sleeper).evaluate("s", QUESTIONS)
        self.assertEqual(len(transport.calls), 2)
        sleeper.assert_called_once_with(0.25)

    def test_request_shape_and_validated_answers(self):
        transport = FakeTransport(ok())
        result = JevClient("key", transport=transport).evaluate("state text", QUESTIONS)
        call = transport.calls[0]
        self.assertEqual(call["url"], "https://api.typesafe.ai/v1/systemone")
        self.assertEqual(call["headers"]["Authorization"], "Bearer key")
        self.assertEqual(call["body"]["model"], "jev-latest")
        self.assertEqual(call["body"]["state"], "state text")
        self.assertEqual(set(call["body"]["questions"]), set(QUESTIONS))
        self.assertEqual(result["model"], "jev-1.13.0")
        self.assertEqual(result["answers"]["urgent"]["noul"], 0.82)
        self.assertEqual(result["usage"], {"input_tokens": 10})
        self.assertEqual(call["body"]["questions"]["severity"]["criteria"], ["Minor", "Severe"])
        self.assertEqual(result["answers"]["severity"]["score"], 0.8)
        self.assertEqual(result["answers"]["severity"]["level"], "high")
        self.assertEqual(result["answers"]["severity"]["level_probabilities"], {"low": 0.2, "high": 0.8})

    def test_missing_api_key_is_config_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(JevConfigError) as caught:
                JevClient()
        self.assertEqual(caught.exception.code, "JEV_CONFIG_MISSING")

    def test_api_key_read_from_environment(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "env-key"}):
            self.assertEqual(JevClient(transport=FakeTransport()).api_key, "env-key")

    def test_question_validation(self):
        invalid = [
            {},
            {"q": {"type": "score", "instructions": "x", "criteria": {str(i): "level" for i in range(11)}}},
            {"q": {"type": "essay", "instructions": "x"}},
            {"q": {"type": "noul", "instructions": " "}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {"only": "one"}}},
            {"q": {"type": "score", "instructions": "x", "criteria": {"a": "", "b": "B"}}},
            {"q": {"type": "choice", "instructions": "x", "criteria": {str(i): "o" for i in range(256)}}},
        ]
        for questions in invalid:
            with self.subTest(questions=str(questions)[:60]):
                with self.assertRaises(JevRequestError):
                    validate_questions(questions)

    def test_malformed_responses_are_rejected(self):
        cases = {
            "missing answer": {key: value for key, value in ANSWERS.items() if key != "urgent"},
            "probability out of range": {**ANSWERS, "urgent": {"type": "noul", "noul": 1.2}},
            "wrong type": {**ANSWERS, "urgent": {"type": "choice", "choice": "billing"}},
            "unknown option": {**ANSWERS, "topic": {"type": "choice", "choice": "sales"}},
            "bad confidence": {**ANSWERS, "topic": {**ANSWERS["topic"], "confidence": "high"}},
            "boolean probability": {**ANSWERS, "urgent": {"type": "noul", "noul": True}},
        }
        for name, answers in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(JevResponseError):
                    JevClient("key", transport=FakeTransport(ok(answers))).evaluate("s", QUESTIONS)
        with self.assertRaises(JevResponseError):
            JevClient("key", transport=FakeTransport((200, b"not json"))).evaluate("s", QUESTIONS)

    def test_rejects_incomplete_or_inconsistent_distributions(self):
        cases = [
            ("topic", {**ANSWERS["topic"], "probabilities": {"billing": 1.0}}),
            ("topic", {**ANSWERS["topic"], "probabilities": {"billing": 0.9, "bug": 0.9}}),
            ("topic", {**ANSWERS["topic"], "choice": "bug"}),
            ("topic", {k: v for k, v in ANSWERS["topic"].items() if k != "confidence"}),
            ("topic", {**ANSWERS["topic"], "choice": []}),
            ("severity", {**ANSWERS["severity"], "score": "high"}),
            ("severity", {**ANSWERS["severity"], "score": True}),
            ("severity", {**ANSWERS["severity"], "score": 1.0}),
            ("severity", {**ANSWERS["severity"], "score": float("nan")}),
            ("severity", {**ANSWERS["severity"], "legend": {"0": "Severe", "1": "Minor"}}),
            ("severity", {**ANSWERS["severity"], "probabilities": {"low": 0.2, "high": 0.8}}),
        ]
        for key, bad in cases:
            with self.subTest(answer=bad), self.assertRaises(JevResponseError):
                JevClient("key", transport=FakeTransport(ok({**ANSWERS, key: bad}))).evaluate("s", QUESTIONS)

    def test_expected_score_is_not_rounded_into_a_symbolic_answer(self):
        # Equal extreme modes have a middle expected value; no middle answer was selected.
        questions = {"q": {"type": "score", "instructions": "Rate", "criteria": {
            "low": "Low", "middle": "Middle", "high": "High",
        }}}
        answer = {"type": "score", "score": 1.0, "confidence": 0.8,
                  "legend": {"0": "Low", "1": "Middle", "2": "High"},
                  "probabilities": {"0": 0.5, "1": 0.0, "2": 0.5}}
        result = JevClient("key", transport=FakeTransport(ok({"q": answer}))).evaluate("s", questions)
        self.assertIsNone(result["answers"]["q"]["level"])
        self.assertEqual(result["answers"]["q"]["score"], 1.0)

    def test_retries_once_on_server_error_or_network_failure(self):
        for first in ((503, {"error": "busy"}), (429, {}), (529, {}), OSError("reset")):
            with self.subTest(first=repr(first)):
                transport = FakeTransport(first, ok())
                JevClient("key", transport=transport).evaluate("s", QUESTIONS)
                self.assertEqual(len(transport.calls), 2)

    def test_no_retry_on_client_error_and_second_failure_raises(self):
        transport = FakeTransport((400, {"error": "bad"}))
        with self.assertRaises(JevRequestError) as caught:
            JevClient("key", transport=transport).evaluate("s", QUESTIONS)
        self.assertEqual((caught.exception.code, len(transport.calls)), ("JEV_HTTP_ERROR", 1))

        transport = FakeTransport((503, {}), (503, {}))
        with self.assertRaises(JevRequestError):
            JevClient("key", transport=transport).evaluate("s", QUESTIONS)
        self.assertEqual(len(transport.calls), 2)

        transport = FakeTransport(OSError("a"), OSError("b"))
        with self.assertRaises(JevRequestError):
            JevClient("key", transport=transport).evaluate("s", QUESTIONS)


if __name__ == "__main__":
    unittest.main()
