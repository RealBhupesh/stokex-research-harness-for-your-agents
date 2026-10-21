"""Fill a deal case's historicals from the point-in-time evidence store.

Field convention:
- ``financial.<line>.<fiscal year>`` for income-statement lines, for example ``financial.revenue.FY26``;
- ``balance_sheet.<item>.<fiscal year>`` for the closing balance sheet of the last historical year.

Each value is the latest observation available at the research cutoff, so a
model built today cannot see a restatement published tomorrow. A missing field
is an error, never a silent fallback to the case file.
"""

import copy
import json
from pathlib import Path

from .case import BALANCE_SHEET_ASSETS, BALANCE_SHEET_CLAIMS, HISTORICAL_LINES, DealCaseError


def case_with_store_historicals(store, case_path, security_id: str, cutoff: str) -> tuple[dict, dict]:
    raw = json.loads(Path(case_path).read_text(encoding="utf-8"))
    case = copy.deepcopy(raw)
    years = case.get("historicals", {}).get("years") or []
    if not years:
        raise DealCaseError("DEAL_CASE_INVALID", "historicals.years must name the fiscal years to load",
                            "$.historicals.years")
    missing, used = [], []

    def fetch(field):
        observation = store.observation_as_of(security_id, field, cutoff)
        if observation is None or observation.get("value_number") is None:
            missing.append(field)
            return None
        used.append({"field": field, "observation_id": observation["observation_id"],
                     "source_id": observation["source_id"], "available_at": observation["available_at"],
                     "quality_status": observation["quality_status"], "value": observation["value_number"]})
        return float(observation["value_number"])

    historicals = {"years": years}
    for line in HISTORICAL_LINES:
        historicals[line] = [fetch(f"financial.{line}.{year}") for year in years]
    balance_sheet = {item: fetch(f"balance_sheet.{item}.{years[-1]}")
                     for item in BALANCE_SHEET_ASSETS + BALANCE_SHEET_CLAIMS}
    if missing:
        raise DealCaseError("STORE_HISTORICALS_MISSING",
                            f"{len(missing)} fields have no observation at {cutoff}: {', '.join(missing[:12])}"
                            + (" ..." if len(missing) > 12 else ""), "$.historicals")
    case["historicals"] = historicals
    case["balance_sheet"] = balance_sheet
    provenance = {"security_id": security_id, "cutoff": cutoff, "fields": len(used),
                  "provisional": sorted(u["field"] for u in used if u["quality_status"] != "VERIFIED"),
                  "observations": used}
    return case, provenance
