"""Command-line interface for the offline point-in-time evidence store."""

import argparse
import csv
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys

from .backtest import build_scorecard, data_fingerprint, load_scorecard, run_backtest
from .jev.client import DEFAULT_MODEL, JevClient, JevError
from .jev.triage import DEFAULT_CONFIDENCE_FLOOR, triage_packet
from .market.importers import KINDS, MarketImportError, import_market_file, parse_date
from .market.queries import coverage
from .market.schema import open_market_db
from .signals.scan import scan, to_markdown
from .signals.setups import SETUPS
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

    jev = commands.add_parser("jev-triage", help="advisory Jev triage of a cutoff evidence packet")
    jev.add_argument("database", type=Path)
    jev.add_argument("security_id")
    jev.add_argument("--cutoff", required=True)
    jev.add_argument("--excerpts", type=Path, help="JSONL of {source_id, text} excerpts")
    jev.add_argument("--confidence-floor", type=float, default=DEFAULT_CONFIDENCE_FLOOR)
    jev.add_argument("--model", default=DEFAULT_MODEL)

    market_import = commands.add_parser("market-import", help="import NSE end-of-day CSV files")
    market_import.add_argument("database", type=Path)
    market_import.add_argument("files", type=Path, nargs="+")
    market_import.add_argument("--kind", default="auto", choices=("auto", *KINDS))
    market_import.add_argument("--options", choices=("none", "near", "near2", "all"), default="near",
                               help="option rows to keep: none, nearest expiry (default), nearest two, or all")
    market_import.add_argument("--available-at", help="override publication timestamp for every row")

    market_status = commands.add_parser("market-status", help="report imported market-data coverage and gaps")
    market_status.add_argument("database", type=Path)

    scanner = commands.add_parser("scan", help="rank short-term setups with hard risk plans at a date")
    scanner.add_argument("database", type=Path)
    scanner.add_argument("--as-of", required=True, help="trade date YYYY-MM-DD (uses end-of-day data)")
    _strategy_arguments(scanner)
    scanner.add_argument("--scorecard", type=Path, help="scorecard JSON from the backtest command")
    scanner.add_argument("--top", type=int, default=10)
    scanner.add_argument("--format", choices=("json", "md"), default="json")

    backtest = commands.add_parser("backtest", help="walk-forward backtest; writes a setup scorecard")
    backtest.add_argument("database", type=Path)
    backtest.add_argument("--from", dest="start", required=True)
    backtest.add_argument("--to", dest="end", required=True)
    _strategy_arguments(backtest)
    backtest.add_argument("--max-positions", type=int, default=5)
    backtest.add_argument("--out", type=Path, help="write the scorecard JSON here")
    backtest.add_argument("--trades", action="store_true", help="include every simulated trade in the output")
    return parser


def _strategy_arguments(command) -> None:
    command.add_argument("--setups", nargs="+", choices=sorted(SETUPS))
    command.add_argument("--capital", type=float)
    command.add_argument("--risk-per-trade", type=float, default=0.01)
    command.add_argument("--min-traded-value", type=float, help="minimum 20-day median traded value in rupees")
    command.add_argument("--min-reward-risk", type=float)
    command.add_argument("--cost-bps", type=float, help="round-trip cost estimate in basis points")
    command.add_argument("--events", type=Path, help="CSV of symbol,date,type catalysts (e.g. RESULTS)")


def _risk_params(args) -> dict:
    params = {"risk_per_trade": args.risk_per_trade}
    if not 0 < args.risk_per_trade <= 0.05:
        raise ValueError("--risk-per-trade must be in (0, 0.05]")
    for name, key in (("capital", "capital"), ("min_traded_value", "min_traded_value"),
                      ("min_reward_risk", "min_reward_risk"), ("cost_bps", "round_trip_cost_bps")):
        value = getattr(args, name)
        if value is not None:
            if value < 0:
                raise ValueError(f"--{name.replace('_', '-')} must be non-negative")
            params[key] = value
    return params


def _read_events(path: Path | None) -> dict:
    if path is None:
        return {}
    events: dict = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), 2):
            try:
                symbol, day, kind = row["symbol"].strip().upper(), parse_date(row["date"]), row["type"].strip().upper()
            except (KeyError, AttributeError) as error:
                raise ValueError(f"{path}:{line_number}: events need symbol,date,type columns") from error
            except Exception as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            events.setdefault(symbol, {})[day] = kind
    return events


def _check_date(value: str, flag: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(f"{flag} must be YYYY-MM-DD") from error


def jev_client_factory(model: str) -> JevClient:
    """Build the Jev client; tests replace this to avoid network calls."""
    return JevClient(model=model)


def _read_excerpts(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    excerpts: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
            source_id, text = (item.get("source_id"), item.get("text")) if isinstance(item, dict) else (None, None)
            if not isinstance(source_id, str) or not source_id or not isinstance(text, str):
                raise ValueError(f"{path}:{line_number}: each line needs string source_id and text")
            if source_id in excerpts:
                raise ValueError(f"{path}:{line_number}: duplicate excerpt for {source_id}")
            excerpts[source_id] = text
    return excerpts


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

    if args.command in {"market-import", "market-status", "scan", "backtest"}:
        return _run_market(args)

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
        if args.command == "jev-triage":
            excerpts = _read_excerpts(args.excerpts)
            client = jev_client_factory(args.model)
            packet = store.evidence_packet(args.security_id, args.cutoff)
            return triage_packet(packet, excerpts, client, confidence_floor=args.confidence_floor)
    raise ValueError(f"Unknown command: {args.command}")


def _run_market(args: argparse.Namespace) -> object:
    if args.command != "market-import" and not args.database.is_file():
        raise ValueError(f"Database does not exist: {args.database}")
    connection = open_market_db(args.database)
    try:
        if args.command == "market-import":
            return [
                import_market_file(connection, path, kind=args.kind,
                                   option_expiries={"none": 0, "near": 1, "near2": 2, "all": None}[args.options],
                                   available_at=args.available_at)
                for path in args.files
            ]
        if args.command == "market-status":
            return coverage(connection)
        events = _read_events(args.events)
        if args.command == "scan":
            as_of = _check_date(args.as_of, "--as-of")
            scorecard = load_scorecard(args.scorecard) if args.scorecard else None
            report = scan(connection, as_of, setups=args.setups, risk_params=_risk_params(args),
                          scorecard=scorecard, events=events, top=args.top)
            return to_markdown(report) if args.format == "md" else report
        start, end = _check_date(args.start, "--from"), _check_date(args.end, "--to")
        if start > end:
            raise ValueError("--from must not be after --to")
        risk = _risk_params(args)
        result = run_backtest(connection, start, end, setups=args.setups, risk_params=risk, events=events,
                              capital=risk.pop("capital", None) or 1_000_000, max_positions=args.max_positions)
        scorecard = build_scorecard(result, data_fingerprint(connection, start, result["period"]["data_through"]))
        if args.out:
            args.out.write_text(json.dumps(scorecard, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                encoding="utf-8")
        summary = {key: result[key] for key in ("period", "capital", "max_positions", "overall", "setups", "notes")}
        summary["portfolio"] = {k: v for k, v in result["portfolio"].items() if k != "equity_curve"}
        summary["scorecard_path"] = str(args.out) if args.out else None
        summary["setup_status"] = {name: entry["status"] for name, entry in scorecard["setups"].items()}
        if args.trades:
            summary["trades"] = result["trades"]
        return summary
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and return its process exit code."""
    try:
        args = _parser().parse_args(argv)
        output = _run(args)
        print(output if isinstance(output, str) else _json_output(output))
        return 0
    except ImportFailure as error:
        print(_json_output(asdict(error)), file=sys.stderr)
    except MarketImportError as error:
        print(_json_output(asdict(error)), file=sys.stderr)
    except JevError as error:
        print(_json_output(_error_payload(error.code, error.message)), file=sys.stderr)
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
