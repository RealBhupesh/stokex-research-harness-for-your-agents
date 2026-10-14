"""Durable local operations shared by CLI and provider integrations."""

from contextlib import ExitStack, closing, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from uuid import uuid4


@contextmanager
def atomic_transaction(connection):
    """Nest safely without committing or rolling back the caller's transaction."""
    name = "stockex_" + uuid4().hex
    connection.execute(f"SAVEPOINT {name}")
    try:
        yield
        connection.execute(f"RELEASE SAVEPOINT {name}")
    except BaseException:
        connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
        connection.execute(f"RELEASE SAVEPOINT {name}")
        raise


def _sync_directory(path):
    """Persist a published filename as well as its contents."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path, payload):
    """Replace a report only after serialization and a durable complete write."""
    text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".stockex-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _sync_directory(destination.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def backup_database(source, destination, *, timeout=30.0):
    """Snapshot a live SQLite DB, verify it, and publish without overwriting."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) \
            or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Backup timeout must be finite and positive")
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"Backup destination already exists: {destination}")
    descriptor, temporary = tempfile.mkstemp(prefix=".stockex-backup-", dir=destination.parent)
    os.close(descriptor)
    try:
        deadline = time.monotonic() + timeout

        def check_deadline(status, remaining, total):
            if time.monotonic() >= deadline:
                raise TimeoutError("Database backup exceeded its time limit")

        with ExitStack() as stack:
            reader = stack.enter_context(closing(sqlite3.connect(
                source.as_uri() + "?mode=ro", uri=True, timeout=min(timeout, 0.1))))
            writer = stack.enter_context(closing(sqlite3.connect(temporary)))
            # Incremental copies allow the deadline to interrupt SQLite's otherwise
            # unbounded retry loop when another connection holds an exclusive lock.
            reader.backup(writer, pages=256, progress=check_deadline, sleep=0.05)
            checks = [row[0] for row in writer.execute("PRAGMA integrity_check")]
            if checks != ["ok"]:
                raise sqlite3.DatabaseError("Backup failed integrity verification")
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
            checksum = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                checksum.update(chunk)
            digest = checksum.hexdigest()
        # A hard link fails if a destination appeared while the backup was running.
        size = Path(temporary).stat().st_size
        os.link(temporary, destination)
        Path(temporary).unlink()
        _sync_directory(destination.parent)
        return {"source": str(source), "backup": str(destination),
                "sha256": digest, "integrity": "ok", "bytes": size}
    finally:
        Path(temporary).unlink(missing_ok=True)
