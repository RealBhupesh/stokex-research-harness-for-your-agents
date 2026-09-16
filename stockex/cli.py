"""Command-line interface for the offline point-in-time evidence store."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys

from .store.database import PointInTimeStore
from .store.importer import ImportFailure, import_jsonl
from .store.records import StoreValidationError
from .store.schema import current_schema_version


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m stockex.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="initialize a SQLite evidence store")
    init.add_argument("database", type=Path)

    ingest = commands.add_parser("ingest", help="atomically ingest a JSONL file")
    ingest.add_argument("database", type=Path)
    ingest.add_argument("source", type=Path)

    as_of = commands.add_parser("as-of", help="query one observation at a cutoff")
    as_of.add_argument("database", type=Path)
    as_of.add_argument("security_id")
    as_of.add_argument("field")
    as_of.add_argument("--cutoff", required=True)

    universe = commands.add_parser("universe", help="reconstruct a universe at a cutoff")
    universe.add_argument("database", type=Path)
    universe.add_argument("universe_id")
    universe.add_argument("--cutoff", required=True)

    packet = commands.add_parser("packet", help="export an evidence packet at a cutoff")
    packet.add_argument("database", type=Path)
    packet.add_argument("security_id")
    packet.add_argument("--cutoff", required=True)
    packet.add_argument("--field", dest="fields", action="append")
    packet.add_argument("--fields", dest="field_list", nargs="+")

    integrity = commands.add_parser("integrity", help="check store integrity")
    integrity.add_argument("database", type=Path)
    return parser


def _json_output(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)


def _error_payload(code: str, message: str, **details: object) -> dict:
    payload = {"code": code, "message": message}
    payload.update(details)
    return payload


def _run(args: argparse.Namespace) -> object:
    if args.command == "init":
        with PointInTimeStore.open(args.database) as store:
            return {
                "database": str(args.database),
                "schema_version": current_schema_version(store.connection),
            }

    if args.command == "ingest":
        with PointInTimeStore.open(args.database) as store:
            return import_jsonl(store, args.source)

    with PointInTimeStore.open(args.database) as store:
        if args.command == "as-of":
            return store.observation_as_of(args.security_id, args.field, args.cutoff)
        if args.command == "universe":
            return store.universe_as_of(args.universe_id, args.cutoff)
        if args.command == "packet":
            fields = list(args.fields or [])
            fields.extend(args.field_list or [])
            return store.evidence_packet(args.security_id, args.cutoff, fields or None)
        if args.command == "integrity":
            return store.integrity_report()
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and return its process exit code."""
    try:
        args = _parser().parse_args(argv)
        print(_json_output(_run(args)))
        return 0
    except ImportFailure as error:
        print(_json_output(asdict(error)), file=sys.stderr)
    except StoreValidationError as error:
        print(_json_output(_error_payload(error.code, error.message, path=error.path)), file=sys.stderr)
    except ValueError as error:
        message = str(error)
        code = "DATABASE_NOT_SQLITE" if message.startswith("Existing database is not a SQLite file:") else "ARGUMENT_INVALID"
        print(_json_output(_error_payload(code, message)), file=sys.stderr)
    except sqlite3.Error as error:
        print(_json_output(_error_payload("SQLITE_ERROR", str(error))), file=sys.stderr)
    except OSError as error:
        print(_json_output(_error_payload("FILESYSTEM_ERROR", str(error))), file=sys.stderr)
    except Exception as error:
        print(_json_output(_error_payload("CLI_ERROR", str(error))), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
