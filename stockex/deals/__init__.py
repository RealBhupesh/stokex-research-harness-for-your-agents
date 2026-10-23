"""PE-grade deal modelling: three statements, LBO, DCF, comps, an Excel model with live formulas and an IC memo."""

from pathlib import Path

from ..operations import atomic_json
from .analysis import analyze
from .case import DealCase, DealCaseError, load_case
from .formula_eval import Book, Evaluator
from .memo import recommendation, to_html, to_markdown
from .workbook import build_workbook


def verify_workbook(path, expectations: dict, *, tolerance: float = 1e-6) -> dict:
    """Recompute every formula in a saved workbook and compare it with the engine's values."""
    evaluator = Evaluator(Book.from_xlsx(path))
    values = evaluator.evaluate_all()
    worst, failures = 0.0, []
    for (sheet, row, col), expected in expectations.items():
        got = evaluator.value(sheet, row, col)
        error = abs(got - expected) if isinstance(got, (int, float)) and not isinstance(got, bool) else float("inf")
        scaled = error / max(1.0, abs(expected))
        worst = max(worst, scaled)
        if scaled > tolerance:
            failures.append({"cell": f"{sheet}!{row},{col}", "expected": expected, "workbook": got})
    return {"formulas": len(values), "engine_checked_cells": len(expectations), "max_relative_error": worst,
            "failures": failures[:20], "ok": not failures}


def build_deal(case_source, out_dir) -> dict:
    """Run the full analysis and write model.xlsx, ic-memo.md, ic-memo.html and results.json."""
    case = load_case(case_source)
    results = analyze(case)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    workbook, expectations = build_workbook(case, results)
    workbook_path = out / "model.xlsx"
    workbook.save(workbook_path)
    verification = verify_workbook(workbook_path, expectations)
    (out / "ic-memo.md").write_text(to_markdown(case, results), encoding="utf-8")
    (out / "ic-memo.html").write_text(to_html(case, results), encoding="utf-8")
    decision = recommendation(case, results)
    payload = {**results, "recommendation": decision, "workbook_verification": verification}
    atomic_json(out / "results.json", payload)
    lbo = results["lbo"]
    return {
        "case": case.name, "company": case.company, "out_dir": str(out),
        "files": [str(out / name) for name in ("model.xlsx", "ic-memo.md", "ic-memo.html", "results.json")],
        "recommendation": decision["decision"], "conditions": decision["conditions"], "failures": decision["failures"],
        "offer_price": lbo["sources_uses"]["offer_price"], "max_bid": results["breakevens"]["max_bid"],
        "entry_multiple": lbo["sources_uses"]["entry_multiple"], "leverage": lbo["sources_uses"]["leverage"],
        "irr": lbo["returns"]["irr"], "moic": lbo["returns"]["moic"],
        "probability_weighted_irr": (results["scenarios"]["probability_weighted"] or {}).get("irr"),
        "dcf_value_per_share": results["dcf"]["gordon"]["value_per_share"],
        "model_checks_ok": lbo["checks"]["ok"], "workbook_verification": {k: v for k, v in verification.items()
                                                                           if k != "failures"},
    }


__all__ = ["DealCase", "DealCaseError", "analyze", "build_deal", "build_workbook", "load_case", "verify_workbook"]
