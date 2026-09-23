import json
import os
import unittest
from unittest import mock

from stockex.jev.client import (
    JevClient, JevConfigError, JevRequestError, JevResponseError, validate_questions,
)


QUESTIONS = {
    "topic": {"type": "choice", "instructions": "Pick one", "criteria": {"billing": "Money", "bug": "Defect"}},
    "urgent": {"type": "noul", "instructions": "Escalate now?"},
    "severity": {"type": "score", "instructions": "How bad?", "criteria": {"low": "Minor", "high": "Severe"}},
}
ANSWERS = {
    "topic": {"type": "choice", "choice": "billing", "probabilities": {"billing": 0.9, "bug": 0.1}, "confidence": 0.9},
    "urgent": {"type": "noul", "noul": 0.82},
    "severity": {"type": "score", "score": "high", "probabilities": {"low": 0.2, "high": 0.8}, "confidence": 0.75},
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

    def test_retries_once_on_server_error_or_network_failure(self):
        for first in ((503, {"error": "busy"}), (429, {}), OSError("reset")):
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
