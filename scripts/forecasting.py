"""Transparent forecast bridges, revisions, scenarios and guidance calibration."""

import math


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def driver_forecast(base_value, drivers):
    """Apply named multiplicative impacts to a reported or normalized base value."""
    base = _finite(base_value, "base_value")
    if not isinstance(drivers, list) or not drivers:
        raise ValueError("drivers must be a nonempty list")
    value = base
    bridge = []
    for index, driver in enumerate(drivers):
        if not isinstance(driver, dict) or not isinstance(driver.get("name"), str) or not driver["name"].strip():
            raise ValueError(f"driver {index} requires a name")
        impact = _finite(driver.get("impact"), f"drivers[{index}].impact")
        if impact <= -1:
            raise ValueError("driver impact must exceed -100%")
        prior = value
        value *= 1 + impact
        bridge.append({"name": driver["name"], "impact": impact, "value_before": prior, "value_after": value})
    return {
        "base_value": base,
        "forecast_value": value,
        "total_change": value / base - 1 if base != 0 else None,
        "bridge": bridge,
        "warning": "Driver arithmetic does not validate the economic assumptions or prevent correlated drivers from being double-counted.",
    }


def estimate_revision(old, new):
    old_value = _finite(old, "old")
    new_value = _finite(new, "new")
    change = new_value - old_value
    direction = "UP" if change > 0 else "DOWN" if change < 0 else "UNCHANGED"
    return {
        "old": old_value,
        "new": new_value,
        "absolute_revision": change,
        "revision_fraction": change / abs(old_value) if old_value else None,
        "direction": direction,
        "warning": "Confirm estimate vintage, accounting basis, dilution and source before interpreting a revision.",
    }


def scenario_distribution(current_price, scenarios):
    price = _finite(current_price, "current_price")
    if price <= 0 or not isinstance(scenarios, list) or len(scenarios) < 2:
        raise ValueError("Positive current_price and at least two scenarios are required")
    rows = []
    probability_presence = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict) or not isinstance(scenario.get("name"), str) or not scenario["name"].strip():
            raise ValueError(f"scenario {index} requires a name")
        value = _finite(scenario.get("value"), f"scenarios[{index}].value")
        if value < 0:
            raise ValueError("Scenario value cannot be negative")
        has_probability = "probability" in scenario
        probability_presence.append(has_probability)
        probability = _finite(scenario["probability"], f"scenarios[{index}].probability") if has_probability else None
        if probability is not None and not 0 <= probability <= 1:
            raise ValueError("Scenario probabilities must be between zero and one")
        rows.append({"name": scenario["name"], "value": value, "return": value / price - 1, "probability": probability})
    if any(probability_presence) and not all(probability_presence):
        raise ValueError("Probabilities must be supplied for every scenario or none")
    if all(probability_presence) and not math.isclose(sum(row["probability"] for row in rows), 1.0, abs_tol=1e-9):
        raise ValueError("Scenario probabilities must sum to one")
    expected_value = sum(row["value"] * row["probability"] for row in rows) if all(probability_presence) else None
    probability_of_loss = sum(row["probability"] for row in rows if row["value"] < price) if all(probability_presence) else None
    return {
        "current_price": price,
        "scenarios": rows,
        "expected_value": expected_value,
        "expected_return": expected_value / price - 1 if expected_value is not None else None,
        "probability_of_loss": probability_of_loss,
        "maximum_scenario_downside": min(row["return"] for row in rows),
        "maximum_scenario_upside": max(row["return"] for row in rows),
        "warning": "Scenario probabilities are analyst assumptions, not observed frequencies or guarantees.",
    }


def guidance_score(records):
    """Score dated management guidance against actual outcomes supplied by the analyst."""
    if not isinstance(records, list) or not records:
        raise ValueError("records must be a nonempty list")
    errors = []
    within = 0
    details = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("metric"), str) or not record["metric"].strip():
            raise ValueError(f"record {index} requires a metric")
        forecast = _finite(record.get("forecast"), f"records[{index}].forecast")
        actual = _finite(record.get("actual"), f"records[{index}].actual")
        tolerance = _finite(record.get("tolerance"), f"records[{index}].tolerance")
        if forecast == 0 or tolerance < 0:
            raise ValueError("Forecast must be nonzero and tolerance nonnegative")
        signed_error = (actual - forecast) / abs(forecast)
        passed = abs(signed_error) <= tolerance
        within += int(passed)
        errors.append(signed_error)
        details.append({"metric": record["metric"], "signed_error_fraction": signed_error, "within_range": passed})
    return {
        "records": len(records),
        "within_range_count": within,
        "within_range_rate": within / len(records),
        "mean_signed_error_fraction": sum(errors) / len(errors),
        "details": details,
        "warning": "Past guidance accuracy is evidence about calibration, not proof of integrity or future execution.",
    }
