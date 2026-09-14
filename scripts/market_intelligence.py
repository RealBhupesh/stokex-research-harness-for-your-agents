"""Deterministic market-context diagnostics without data retrieval or causal claims."""

import math
import statistics


def _finite(value, name):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _return_series(values, name):
    series = [_finite(value, name) for value in values]
    if not series or any(value <= -1 for value in series):
        raise ValueError(f"{name} must be nonempty and every return must exceed -100%")
    return series


def compound_return(returns):
    """Compound decimal periodic returns into a holding-period return."""
    series = _return_series(returns, "returns")
    return math.prod(1 + value for value in series) - 1


def price_move_attribution(asset_returns, benchmark_returns, sector_returns,
                           peer_return_series):
    """Decompose a move relative to comparison series while preserving unexplained residuals."""
    asset = _return_series(asset_returns, "asset_returns")
    benchmark = _return_series(benchmark_returns, "benchmark_returns")
    sector = _return_series(sector_returns, "sector_returns")
    if len(asset) != len(benchmark) or len(asset) != len(sector):
        raise ValueError("Asset, benchmark and sector series must have equal lengths")
    if not peer_return_series:
        raise ValueError("At least one peer return series is required")
    peers = [_return_series(values, "peer_return_series") for values in peer_return_series]
    if any(len(values) != len(asset) for values in peers):
        raise ValueError("Every peer series must match the asset series length")

    asset_total = compound_return(asset)
    benchmark_total = compound_return(benchmark)
    sector_total = compound_return(sector)
    peer_totals = [compound_return(values) for values in peers]
    peer_median = statistics.median(peer_totals)
    return {
        "n_periods": len(asset),
        "asset_total_return": asset_total,
        "benchmark_total_return": benchmark_total,
        "sector_total_return": sector_total,
        "peer_median_total_return": peer_median,
        "relative_to_benchmark": asset_total - benchmark_total,
        "residual_vs_sector": asset_total - sector_total,
        "residual_vs_peers": asset_total - peer_median,
        "attribution_status": "UNEXPLAINED",
        "warning": (
            "Relative performance narrows hypotheses but does not establish causality. "
            "Use dated events, exposure evidence and counterfactuals before assigning a cause."
        ),
    }


def driver_materiality(driver):
    """Check whether a proposed world or market driver has an evidenced transmission path."""
    if not isinstance(driver, dict):
        raise ValueError("driver must be an object")
    required = ("name", "exposure", "magnitude", "transmission_path", "source_ids")
    missing = []
    for field in required:
        value = driver.get(field)
        if field == "source_ids":
            if not isinstance(value, list) or not value:
                missing.append(field)
        elif not isinstance(value, str) or not value.strip() or value.strip().lower() == "unknown":
            missing.append(field)
    material = not missing
    return {
        "name": driver.get("name"),
        "material": material,
        "classification": "MATERIAL" if material else "NOT MATERIAL",
        "missing": missing,
        "warning": (
            "Materiality confirms a documented pathway, not the direction or size of a future stock move."
        ),
    }
