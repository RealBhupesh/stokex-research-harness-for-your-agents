"""SQLite cache of Jev judgments so repeated backtests are cheap and deterministic."""

from datetime import datetime, timezone
import json
import sqlite3


_TABLE = """
CREATE TABLE IF NOT EXISTS jev_judgments (
    input_sha256 TEXT NOT NULL,
    bank_version TEXT NOT NULL,
    model TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    model_returned TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (input_sha256, bank_version, model)
)
"""


class JevCache:
    """Judgments keyed by (input hash, question bank version, requested model)."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        connection.execute(_TABLE)
        connection.commit()

    def get(self, input_sha256: str, bank_version: str, model: str) -> dict | None:
        row = self.connection.execute(
            "SELECT answers_json, model_returned FROM jev_judgments "
            "WHERE input_sha256 = ? AND bank_version = ? AND model = ?",
            (input_sha256, bank_version, model),
        ).fetchone()
        if row is None:
            return None
        return {"answers": json.loads(row[0]), "model": row[1]}

    def put(self, input_sha256: str, bank_version: str, model: str, answers: dict, model_returned: str) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO jev_judgments VALUES (?, ?, ?, ?, ?, ?)",
            (input_sha256, bank_version, model, json.dumps(answers, sort_keys=True), model_returned,
             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        self.connection.commit()
