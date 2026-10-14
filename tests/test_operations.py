"""Durability and failure isolation for operational file publication."""

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from stockex.operations import atomic_json, atomic_transaction, backup_database


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.sqlite3"
        with sqlite3.connect(self.source) as db:
            db.execute("CREATE TABLE sample(value TEXT)")
            db.execute("INSERT INTO sample VALUES ('original')")

    def test_busy_backup_times_out_without_publishing_or_leaking_tempfiles(self):
        destination = self.root / "backup.sqlite3"
        db = sqlite3.connect(self.source)
        self.addCleanup(db.close)
        db.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with self.assertRaisesRegex(TimeoutError, "time limit"):
            backup_database(self.source, destination, timeout=0.02)
        self.assertLess(time.monotonic() - started, 2)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob(".stockex-*")), [])
        db.rollback()
        # A failed attempt leaves the source and destination usable.
        backup_database(self.source, destination)

    def test_failure_opening_backup_writer_closes_reader(self):
        reader = Mock()
        with patch("stockex.operations.sqlite3.connect", side_effect=[reader, OSError("disk failed")]):
            with self.assertRaisesRegex(OSError, "disk failed"):
                backup_database(self.source, self.root / "backup.sqlite3")
        reader.close.assert_called_once_with()
        self.assertEqual(list(self.root.glob(".stockex-*")), [])

    def test_backup_publication_race_never_overwrites_other_file(self):
        destination = self.root / "backup.sqlite3"
        def collision(source, target):
            Path(target).write_text("another backup")
            raise FileExistsError("already exists")
        with patch("stockex.operations.os.link", side_effect=collision):
            with self.assertRaises(FileExistsError):
                backup_database(self.source, destination)
        self.assertEqual(destination.read_text(), "another backup")
        self.assertEqual(list(self.root.glob(".stockex-*")), [])

    def test_verified_backup_hash_matches_published_bytes_and_syncs_directory(self):
        destination = self.root / "backup.sqlite3"
        with patch("stockex.operations._sync_directory") as sync:
            report = backup_database(self.source, destination)
        sync.assert_called_once_with(self.root)
        self.assertEqual(report["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(report["bytes"], destination.stat().st_size)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute("SELECT value FROM sample").fetchone(), ("original",))

    def test_report_syncs_published_directory_and_rejects_nonfinite_without_changes(self):
        destination = self.root / "report.json"
        with patch("stockex.operations._sync_directory") as sync:
            atomic_json(destination, {"value": 1})
        sync.assert_called_once_with(self.root)
        with self.assertRaises(ValueError):
            atomic_json(destination, {"value": float("nan")})
        self.assertEqual(json.loads(destination.read_text()), {"value": 1})
        self.assertEqual(list(self.root.glob(".stockex-*")), [])

    def test_timeout_validation_does_not_create_files(self):
        for value in (True, False, None, "1", 0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=value), self.assertRaises(ValueError):
                backup_database(self.source, self.root / "backup.sqlite3", timeout=value)
        self.assertEqual(list(self.root.glob(".stockex-*")), [])

    def test_cancelled_nested_transaction_preserves_outer_work(self):
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT INTO sample VALUES ('outer')")
            with self.assertRaises(KeyboardInterrupt):
                with atomic_transaction(db):
                    db.execute("INSERT INTO sample VALUES ('inner')")
                    raise KeyboardInterrupt()
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.execute("SELECT value FROM sample").fetchall(),
                             [("original",), ("outer",)])
