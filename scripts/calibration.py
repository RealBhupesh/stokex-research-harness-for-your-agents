"""Freeze-aware thesis transitions and analyst process diagnostics."""

from collections import Counter
from datetime import datetime
import math


STATUSES = {"ACTIVE", "CONFIRMED", "WEAKENED", "INVALIDATED", "CLOSED"}
ALLOWED_TRANSITIONS = {
    "ACTIVE": {"CONFIRMED", "WEAKENED", "INVALIDATED", "CLOSED"},
    "CONFIRMED": {"ACTIVE", "WEAKENED", "INVALIDATED", "CLOSED"},
    "WEAKENED": {"ACTIVE", "CONFIRMED", "INVALIDATED", "CLOSED"},
    "INVALIDATED": {"CLOSED"},
    "CLOSED": set(),
}


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _aware_timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_transition(old_status, new_status, trigger):
    """Require a sourced, dated reason for every permitted thesis-state change."""
    status_valid = old_status in STATUSES and new_status in STATUSES
    transition_allowed = status_valid and new_status in ALLOWED_TRANSITIONS[old_status]
    trigger_valid = (
        isinstance(trigger, dict)
        and all(isinstance(trigger.get(name), str) and trigger[name].strip()
                for name in ("id", "source_id", "reason"))
        and _aware_timestamp(trigger.get("occurred_at"))
    )
    errors = []
    if not status_valid:
        errors.append("STATUS_INVALID")
    elif not transition_allowed:
        errors.append("TRANSITION_NOT_ALLOWED")
    if not trigger_valid:
        errors.append("EVIDENCE_TRIGGER_REQUIRED")
    return {
        "valid": not errors,
        "old_status": old_status,
        "new_status": new_status,
        "trigger": trigger if isinstance(trigger, dict) else {},
        "errors": errors,
    }


def forecast_error(forecast, actual):
    forecast_value = _finite(forecast, "forecast")
    actual_value = _finite(actual, "actual")
    signed = forecast_value - actual_value
    direction = "OVER" if signed > 0 else "UNDER" if signed < 0 else "EXACT"
    return {
        "forecast": forecast_value,
        "actual": actual_value,
        "signed_error": signed,
        "direction": direction,
        "absolute_percentage_error": abs(signed) / abs(actual_value) if actual_value else None,
        "warning": "A forecast error should be attributed to drivers and information available at the frozen cutoff.",
    }


def process_score(records, minimum_reliable_sample=20):
    """Aggregate closed prediction records without treating a small sample as strategy evidence."""
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a nonempty list")
    minimum = int(_finite(minimum_reliable_sample, "minimum_reliable_sample"))
    if minimum <= 0:
        raise ValueError("minimum_reliable_sample must be positive")
    closed = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"record {index} must be an object")
        outcome = record.get("decision_outcome")
        if outcome not in {"SUCCESS", "FAILURE", "OPEN"}:
            raise ValueError(f"record {index} has invalid decision_outcome")
        if outcome != "OPEN":
            error = _finite(record.get("forecast_error_fraction"), f"records[{index}].forecast_error_fraction")
            process_errors = record.get("process_errors")
            if not isinstance(process_errors, list) or any(not isinstance(value, str) or not value for value in process_errors):
                raise ValueError(f"record {index} process_errors must be a string list")
            closed.append({"outcome": outcome, "forecast_error": error, "process_errors": process_errors})
    if not closed:
        raise ValueError("At least one closed record is required")
    counts = Counter(error for record in closed for error in record["process_errors"])
    successes = sum(record["outcome"] == "SUCCESS" for record in closed)
    return {
        "total_records": len(records),
        "closed_records": len(closed),
        "success_rate": successes / len(closed),
        "mean_absolute_forecast_error": sum(abs(record["forecast_error"]) for record in closed) / len(closed),
        "process_error_counts": dict(sorted(counts.items())),
        "small_sample_warning": len(closed) < minimum,
        "warning": "Do not change thresholds from a small, selected or non-point-in-time sample.",
    }
