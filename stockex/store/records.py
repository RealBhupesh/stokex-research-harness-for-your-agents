"""Immutable, validated records for the point-in-time evidence store."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
import math
import re
from typing import Any, Union


class StoreValidationError(ValueError):
    def __init__(self, code: str, path: str, message: str):
        super().__init__(message)
        self.code, self.path, self.message = code, path, message


def normalize_timestamp(value: str, path: str) -> str:
    if not isinstance(value, str):
        raise StoreValidationError("TIMESTAMP_INVALID", path, "Timestamp must be an ISO 8601 string")
    # Inspect both wall-clock and offset fractions before datetime can truncate them.
    if re.search(r"[.,][0-9]*[1-9]", value):
        raise StoreValidationError(
            "TIMESTAMP_PRECISION_UNSUPPORTED", path, "Timestamps must use whole-second precision"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise StoreValidationError("TIMESTAMP_INVALID", path, "Timestamp must be a valid ISO 8601 value")
    if parsed.tzinfo is None:
        raise StoreValidationError("TIMESTAMP_NAIVE", path, "Timestamp must include a timezone")
    if parsed.microsecond:
        raise StoreValidationError(
            "TIMESTAMP_PRECISION_UNSUPPORTED", path, "Timestamps must use whole-second precision"
        )
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class IssuerRecord:
    issuer_id: str
    legal_name: str | None = None
    cin: str | None = None
    lei: str | None = None
    status: str | None = None
    metadata_json: str = "{}"
    canonical_json: str = ""


@dataclass(frozen=True)
class SecurityRecord:
    security_id: str
    issuer_id: str
    isin: str | None = None
    exchange: str | None = None
    instrument_type: str | None = None
    canonical_json: str = ""


@dataclass(frozen=True)
class SecuritySymbolRecord:
    symbol_id: str
    security_id: str
    symbol: str
    valid_from: str | None = None
    valid_to: str | None = None
    source_id: str | None = None
    canonical_json: str = ""


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    publisher: str | None = None
    source_class: str | None = None
    uri: str | None = None
    published_at: str | None = None
    available_at: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
    metadata_json: str = "{}"
    canonical_json: str = ""


@dataclass(frozen=True)
class ObservationRecord:
    observation_id: str
    security_id: str
    field: str
    value_type: str
    value_number: float | int | None = None
    value_text: str | None = None
    value_boolean: bool | None = None
    value_date: str | None = None
    value_json: Any = None
    unit: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    source_id: str | None = None
    available_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    revision_of: str | None = None
    revision_number: int | None = None
    quality_status: str | None = None
    metadata_json: str = "{}"
    canonical_json: str = ""


@dataclass(frozen=True)
class UniverseMembershipRecord:
    membership_id: str
    universe_id: str
    security_id: str
    effective_from: str | None = None
    effective_to: str | None = None
    source_id: str | None = None
    metadata_json: str = "{}"
    canonical_json: str = ""


@dataclass(frozen=True)
class CorporateActionRecord:
    action_id: str
    security_id: str
    action_type: str | None = None
    source_id: str | None = None
    available_at: str | None = None
    ex_date: str | None = None
    record_date: str | None = None
    effective_date: str | None = None
    ratio: float | None = None
    cash_amount: float | None = None
    currency: str | None = None
    status: str | None = None
    metadata_json: str = "{}"
    canonical_json: str = ""


Record = Union[IssuerRecord, SecurityRecord, SecuritySymbolRecord, SourceRecord,
               ObservationRecord, UniverseMembershipRecord, CorporateActionRecord]

_TYPES = {
    "issuer": IssuerRecord, "security": SecurityRecord, "security_symbol": SecuritySymbolRecord,
    "source": SourceRecord, "observation": ObservationRecord,
    "universe_membership": UniverseMembershipRecord, "corporate_action": CorporateActionRecord,
}
_TIMESTAMPS = {
    "published_at", "available_at", "retrieved_at", "valid_from", "valid_to",
    "period_start", "period_end", "effective_from", "effective_to", "ex_date",
    "record_date", "effective_date", "value_date",
}
_ENUMS = {"exchange": {"NSE", "BSE"}, "status": {"ACTIVE", "MERGED", "DELISTED", "DISSOLVED", "UNKNOWN"}, "quality_status": {"VERIFIED", "PROVISIONAL", "ASSUMED_LAG", "QUARANTINED"},
          "value_type": {"NUMBER", "TEXT", "BOOLEAN", "DATE", "JSON"}}
_REQUIRED = {
    "issuer": ("issuer_id",), "security": ("security_id", "issuer_id"),
    "security_symbol": ("symbol_id", "security_id", "symbol"), "source": ("source_id", "publisher"),
    "observation": ("observation_id", "security_id", "field", "value_type", "source_id", "available_at"),
    "universe_membership": ("membership_id", "universe_id", "security_id"),
    "corporate_action": ("action_id", "security_id"),
}


def _fail(code: str, path: str, message: str):
    raise StoreValidationError(code, path, message)


def _depth(value: Any, level: int = 0) -> int:
    if isinstance(value, dict):
        return max([level] + [_depth(v, level + 1) for v in value.values()])
    if isinstance(value, list):
        return max([level] + [_depth(v, level + 1) for v in value])
    return level


def validate_envelope(envelope: dict) -> Record:
    if not isinstance(envelope, dict): _fail("ENVELOPE_INVALID", "envelope", "Envelope must be an object")
    if envelope.get("schema_version") != 1: _fail("SCHEMA_VERSION_UNSUPPORTED", "schema_version", "Unsupported schema version")
    record_type = envelope.get("record_type")
    if not isinstance(record_type, str) or record_type not in _TYPES:
        _fail("RECORD_TYPE_UNSUPPORTED", "record_type", "Unsupported record type")
    raw = envelope.get("record")
    if not isinstance(raw, dict): _fail("RECORD_INVALID", "record", "Record must be an object")
    for key in _REQUIRED[record_type]:
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            _fail(f"{key.upper()}_MISSING", f"record.{key}", f"{key} is required")
    for key, allowed in _ENUMS.items():
        if key == "status" and record_type != "issuer":
            continue
        if key in raw and (not isinstance(raw[key], str) or raw[key] not in allowed):
            _fail("ENUM_INVALID", f"record.{key}", f"Invalid {key}")
    normalized = dict(raw)
    for key in _TIMESTAMPS:
        if normalized.get(key) is not None:
            normalized[key] = normalize_timestamp(normalized[key], f"record.{key}")
    for start, end in (("valid_from", "valid_to"), ("period_start", "period_end"), ("effective_from", "effective_to")):
        if normalized.get(start) and normalized.get(end) and normalized[end] <= normalized[start]:
            _fail("INTERVAL_INVALID", f"record.{end}", "Interval end must be after start")
    metadata = normalized.pop("metadata", {})
    if metadata is None: metadata = {}
    if not isinstance(metadata, (dict, list)): _fail("METADATA_INVALID", "record.metadata", "Metadata must be JSON-compatible")
    if _depth(metadata) > 12: _fail("METADATA_NESTING_TOO_DEEP", "record.metadata", "Metadata nesting exceeds 12 levels")
    try:
        metadata_text = canonical_json(metadata)
    except (TypeError, ValueError):
        _fail("METADATA_INVALID", "record.metadata", "Metadata must be JSON-compatible")
    if len(metadata_text.encode("utf-8")) > 64 * 1024: _fail("METADATA_TOO_LARGE", "record.metadata", "Metadata exceeds 64 KiB")
    normalized["metadata_json"] = metadata_text
    if record_type == "observation":
        value_type = normalized["value_type"]
        value_fields = {"NUMBER": "value_number", "TEXT": "value_text", "BOOLEAN": "value_boolean", "DATE": "value_date", "JSON": "value_json"}
        present = [k for k in value_fields.values() if k in normalized and normalized[k] is not None]
        if len(present) != 1 or present[0] != value_fields[value_type]: _fail("VALUE_REPRESENTATION_INVALID", "record", "Exactly one typed value representation is required")
        if value_type == "NUMBER" and (not isinstance(normalized["value_number"], (int, float)) or isinstance(normalized["value_number"], bool) or not math.isfinite(normalized["value_number"])): _fail("VALUE_REPRESENTATION_INVALID", "record.value_number", "Number must be finite")
        if value_type == "NUMBER" and (not isinstance(normalized.get("unit"), str) or not normalized["unit"].strip()): _fail("UNIT_REQUIRED", "record.unit", "Numeric observations require a unit")
        if value_type == "BOOLEAN" and not isinstance(normalized["value_boolean"], bool): _fail("VALUE_REPRESENTATION_INVALID", "record.value_boolean", "Boolean observations require a boolean")
        if value_type == "JSON":
            try:
                canonical_json(normalized["value_json"])
            except (TypeError, ValueError):
                _fail("VALUE_REPRESENTATION_INVALID", "record.value_json", "JSON observations require a JSON-compatible value")
    if record_type == "source" and normalized.get("published_at") and normalized.get("available_at") and normalized["published_at"] > normalized["available_at"]:
        _fail("TIMESTAMP_ORDER_INVALID", "record.available_at", "Source timestamps are out of order")
    if record_type == "source" and normalized.get("available_at") and normalized.get("retrieved_at") and normalized["available_at"] > normalized["retrieved_at"]:
        _fail("TIMESTAMP_ORDER_INVALID", "record.retrieved_at", "Source timestamps are out of order")
    allowed = {f.name for f in fields(_TYPES[record_type])}
    if "metadata_json" not in allowed:
        normalized.pop("metadata_json", None)
    unknown = set(normalized) - allowed
    if unknown:
        _fail("FIELD_UNSUPPORTED", f"record.{sorted(unknown)[0]}", "Unsupported record field")
    canonical_record = dict(normalized)
    canonical_record.pop("canonical_json", None)
    canonical_record.pop("metadata_json", None)
    canonical_record["metadata"] = metadata
    normalized["canonical_json"] = canonical_json({"record_type": record_type, "schema_version": 1, "record": canonical_record})
    return _TYPES[record_type](**normalized)
