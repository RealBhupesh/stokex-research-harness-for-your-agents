"""Bounded-memory, atomic imports for JSONL evidence envelopes."""

from dataclasses import FrozenInstanceError, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .database import PointInTimeStore
from .records import StoreValidationError, validate_envelope


@dataclass(frozen=True)
class ImportFailure(Exception):
    """A stable, line-addressable failure while importing one JSONL file."""

    path: str
    line: int
    code: str
    message: str

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


# ``BaseException`` assigns ``__traceback__`` while unwinding.  A fully
# frozen dataclass blocks that interpreter bookkeeping, so retain frozen field
# semantics while allowing exception runtime attributes to be assigned.
def _exception_setattr(self: ImportFailure, name: str, value: object) -> None:
    if name in {"path", "line", "code", "message"} and name in self.__dict__:
        raise FrozenInstanceError(f"cannot assign to field '{name}'")
    object.__setattr__(self, name, value)


ImportFailure.__setattr__ = _exception_setattr


def _failure(path: Path, line: int, code: str, message: str) -> ImportFailure:
    return ImportFailure(str(path), line, code, message)


def _reject_nonstandard_json_constant(value: str) -> object:
    raise ValueError(f"Non-standard JSON constant: {value}")


def _record_lines(
    path: Path, digest: "hashlib._Hash", *, defer_errors: bool = False
) -> Iterator[tuple[int, object]]:
    try:
        handle = path.open("rb")
    except OSError as error:
        raise _failure(path, 1, "FILE_READ_ERROR", str(error)) from error

    first_failure: ImportFailure | None = None
    try:
        with handle:
            for line_number, raw_line in enumerate(handle, 1):
                digest.update(raw_line)
                try:
                    if not raw_line.strip():
                        raise _failure(path, line_number, "BLANK_LINE", "Blank JSONL records are not allowed")
                    try:
                        text = raw_line.decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise _failure(path, line_number, "UTF8_INVALID", "Input must be valid UTF-8") from error
                    try:
                        envelope = json.loads(text, parse_constant=_reject_nonstandard_json_constant)
                    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                        raise _failure(path, line_number, "JSON_INVALID", "Line is not valid JSON") from error
                    try:
                        record = validate_envelope(envelope)
                    except StoreValidationError as error:
                        raise _failure(path, line_number, error.code, error.message) from error
                except ImportFailure as error:
                    if not defer_errors:
                        raise
                    if first_failure is None:
                        first_failure = error
                    continue
                yield line_number, record
    except OSError as error:
        raise _failure(path, 1, "FILE_READ_ERROR", str(error)) from error
    if first_failure is not None:
        raise first_failure


def import_jsonl(store: PointInTimeStore, path: str | Path) -> dict:
    """Validate and ingest one complete JSONL file in a single transaction.

    The first pass performs all decoding and validation while computing a digest.
    The second pass streams the records into one transaction and computes the
    digest again; no transaction is committed until the digests agree.
    """
    source_path = Path(path)
    first_digest = hashlib.sha256()
    # Pass one is intentionally free of store operations and therefore cannot
    # partially mutate the database.
    first_failure: ImportFailure | None = None
    try:
        for _line_number, _record in _record_lines(
            source_path, first_digest, defer_errors=True
        ):
            pass
    except ImportFailure as error:
        first_failure = error
    if first_failure is not None:
        raise first_failure

    inserted = 0
    unchanged = 0
    second_digest = hashlib.sha256()
    try:
        before_second_pass = source_path.stat()
    except OSError as error:
        raise _failure(source_path, 1, "FILE_READ_ERROR", str(error)) from error
    try:
        with store.transaction():
            pass2_failure: ImportFailure | None = None
            try:
                records = _record_lines(source_path, second_digest, defer_errors=True)
                for line_number, record in records:
                    if pass2_failure is not None:
                        continue
                    try:
                        result = store.ingest(record, commit=False)
                    except StoreValidationError as error:
                        pass2_failure = _failure(source_path, line_number, error.code, error.message)
                        continue
                    except sqlite3.Error as error:
                        pass2_failure = _failure(source_path, line_number, "SQLITE_ERROR", str(error))
                        continue
                    if result.status == "INSERTED":
                        inserted += 1
                    elif result.status == "UNCHANGED":
                        unchanged += 1
            except ImportFailure as error:
                pass2_failure = pass2_failure or error
            try:
                after_second_pass = source_path.stat()
            except OSError as error:
                raise _failure(source_path, 1, "FILE_READ_ERROR", str(error)) from error
            # Always compare after consuming the second stream.  A malformed
            # edit must report file-change detection (and still roll back) if
            # it made the bytes differ between passes.
            file_changed = (
                second_digest.digest() != first_digest.digest()
                or before_second_pass.st_dev != after_second_pass.st_dev
                or before_second_pass.st_ino != after_second_pass.st_ino
                or before_second_pass.st_size != after_second_pass.st_size
                or before_second_pass.st_mtime_ns != after_second_pass.st_mtime_ns
            )
            if file_changed:
                raise _failure(
                    source_path,
                    1,
                    "FILE_CHANGED_DURING_IMPORT",
                    "The JSONL file changed between validation and ingestion",
                )
            if pass2_failure is not None:
                raise pass2_failure
    except ImportFailure:
        raise
    except OSError as error:
        raise _failure(source_path, 1, "FILE_READ_ERROR", str(error)) from error
    except sqlite3.Error as error:
        raise _failure(source_path, 1, "SQLITE_ERROR", str(error)) from error

    return {"inserted": inserted, "unchanged": unchanged}
