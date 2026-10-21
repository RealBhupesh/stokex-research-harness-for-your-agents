"""Deal cases for tests: the shipped demo and a small textbook LBO whose answers are checkable by hand."""

import copy
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "deals" / "project-saffron.json"


def demo_raw() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))


def textbook_raw(*, sweep: bool = False, pik: float = 0.0, years: int = 3) -> dict:
    """EBITDA 20 flat, no tax, capex, D&A or working capital; bought at 8x (160) with 4x (80) of 10% debt."""
    flat = lambda v: [v] * years  # noqa: E731
    return {
        "schema_version": 1, "name": "Textbook", "company": "Textbook Ltd", "illustrative": True,
        "historicals": {"years": ["FY25", "FY26"], "revenue": [100.0, 100.0], "cogs": [50.0, 50.0],
                        "opex": [30.0, 30.0], "da": [0.0, 0.0], "finance_cost": [0.0, 0.0],
                        "other_income": [0.0, 0.0], "tax": [0.0, 0.0]},
        "balance_sheet": {"cash": 0.0, "receivables": 0.0, "inventory": 0.0, "other_current_assets": 0.0,
                          "ppe": 100.0, "intangibles": 0.0, "other_non_current_assets": 0.0, "payables": 0.0,
                          "other_current_liabilities": 0.0, "debt": 0.0, "other_non_current_liabilities": 0.0,
                          "equity": 100.0},
        "market": {"unaffected_price": 16.0, "diluted_shares": 10.0, "week52_low": 12.0, "week52_high": 18.0},
        "projection": {"years": [f"FY{27 + i}" for i in range(years)], "tax_rate": 0.0, "cash_yield": 0.0},
        "scenarios": {"base": {"revenue_growth": flat(0.0), "gross_margin": flat(0.5), "opex_pct": flat(0.3),
                               "da_pct": flat(0.0), "capex_pct": flat(0.0), "receivable_days": flat(0),
                               "inventory_days": flat(0), "payable_days": flat(0), "exit_multiple": 8.0}},
        "transaction": {"offer_premium": 0.0, "transaction_fee_pct": 0.0, "financing_fee_pct": 0.0,
                        "minimum_cash": 0.0, "rollover_pct": 0.0, "holding_years": years, "exit_cost_pct": 0.0,
                        "management_incentive_pct": 0.0, "hurdle_irr": 0.2, "target_moic": 2.0, "sweep_pct": 1.0},
        "debt": [{"name": "Term loan", "kind": "bullet", "ebitda_multiple": 4.0, "cash_rate": 0.10, "pik_rate": pik,
                  "amortization": flat(0.0), "sweep": sweep, "subject_to_interest_cap": False}],
        "revolver": {"commitment": 10.0, "cash_rate": 0.08, "undrawn_fee": 0.0},
        "covenants": {"max_net_leverage": flat(6.0), "min_interest_cover": 1.5, "min_dscr": 1.0},
        "tax": {"interest_cap_pct_ebitda": 0.3, "interest_cap_threshold": 1.0},
        "valuation": {"risk_free": 0.07, "equity_risk_premium": 0.07, "size_premium": 0.0,
                      "pre_tax_cost_of_debt": 0.09, "target_debt_to_capital": 0.2, "terminal_growth": 0.04,
                      "exit_multiple": 8.0, "mid_year": False,
                      "peer_betas": [{"name": "P1", "levered_beta": 1.2, "debt_to_equity": 0.5, "tax_rate": 0.25},
                                     {"name": "P2", "levered_beta": 0.9, "debt_to_equity": 0.0, "tax_rate": 0.25},
                                     {"name": "P3", "levered_beta": 1.0, "debt_to_equity": 0.25, "tax_rate": 0.25}]},
        "comps": [{"name": f"C{i}", "market_cap": 100.0 * i, "net_debt": 10.0, "revenue": 50.0 * i,
                   "ebitda": 10.0 * i, "net_income": 6.0 * i} for i in (1, 2, 3)],
        "precedents": [{"target": f"T{i}", "acquirer": "Sponsor", "year": "FY24", "ev_ebitda": 7.0 + i,
                        "premium": 0.2 + 0.05 * i} for i in (1, 2, 3)],
        "monte_carlo": {"paths": 50, "seed": 3},
    }


def modified(raw: dict, **changes) -> dict:
    out = copy.deepcopy(raw)
    for path, value in changes.items():
        target = out
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        last = keys[-1]
        target[int(last) if last.isdigit() else last] = value
    return out
