"""Deal cases: the validated inputs every model in ``stockex.deals`` reads.

A case is one JSON document (see ``examples/deals/project-saffron.json``).
Money is in one currency unit (INR crore by convention), shares in one share
unit (crore shares) and rates as decimals. Validation fails loudly with a
code and a JSON path, because a model built on a silently wrong input is
worse than no model.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path


CASE_SCHEMA_VERSION = 1
DRIVERS = ("revenue_growth", "gross_margin", "opex_pct", "da_pct", "capex_pct",
           "receivable_days", "inventory_days", "payable_days")
HISTORICAL_LINES = ("revenue", "cogs", "opex", "da", "finance_cost", "other_income", "tax")
BALANCE_SHEET_ASSETS = ("cash", "receivables", "inventory", "other_current_assets", "ppe", "intangibles",
                        "other_non_current_assets")
BALANCE_SHEET_CLAIMS = ("payables", "other_current_liabilities", "debt", "other_non_current_liabilities", "equity")
SCENARIOS = ("base", "upside", "downside")


class DealCaseError(ValueError):
    def __init__(self, code: str, message: str, path: str):
        super().__init__(f"{path}: {message}")
        self.code, self.message, self.path = code, message, path


def _fail(path: str, message: str, code: str = "DEAL_CASE_INVALID"):
    raise DealCaseError(code, message, path)


def _number(value, path: str, *, low: float | None = None, high: float | None = None,
            positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(path, "must be a finite number")
    value = float(value)
    if positive and value <= 0:
        _fail(path, "must be positive")
    if low is not None and value < low:
        _fail(path, f"must be >= {low}")
    if high is not None and value > high:
        _fail(path, f"must be <= {high}")
    return value


def _series(value, path: str, length: int, **bounds) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        _fail(path, f"must be a list of {length} numbers")
    return [_number(item, f"{path}[{index}]", **bounds) for index, item in enumerate(value)]


def _object(value, path: str) -> dict:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _text(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    return value


@dataclass(frozen=True)
class Tranche:
    name: str
    kind: str                 # "amortizing" or "bullet"
    ebitda_multiple: float    # sized on LTM EBITDA at close
    cash_rate: float
    pik_rate: float
    amortization: tuple       # scheduled repayment per year, share of the original principal
    sweep: bool               # receives excess cash after the revolver
    subject_to_interest_cap: bool


@dataclass(frozen=True)
class DealCase:
    raw: dict
    name: str
    company: str
    illustrative: bool
    historical_years: tuple
    projection_years: tuple
    historicals: dict
    balance_sheet: dict
    market: dict
    projection: dict
    scenarios: dict           # name -> full driver arrays + exit_multiple + probability
    transaction: dict
    tranches: tuple
    revolver: dict
    covenants: dict
    tax: dict
    valuation: dict
    comps: tuple
    precedents: tuple
    monte_carlo: dict

    @property
    def years(self) -> int:
        return len(self.projection_years)

    def drivers(self, scenario: str = "base") -> dict:
        if scenario not in self.scenarios:
            _fail("scenario", f"unknown scenario {scenario!r}; expected one of {sorted(self.scenarios)}")
        return self.scenarios[scenario]

    @property
    def ltm_ebitda(self) -> float:
        h = self.historicals
        return h["revenue"][-1] - h["cogs"][-1] - h["opex"][-1]


def load_case(source) -> DealCase:
    """Load and validate a case from a path or an already-parsed dict."""
    if isinstance(source, (str, Path)):
        try:
            raw = json.loads(Path(source).read_text(encoding="utf-8"))
        except ValueError as error:
            _fail(str(source), f"invalid JSON: {error}", "DEAL_CASE_JSON_INVALID")
    else:
        raw = source
    raw = _object(raw, "$")
    if raw.get("schema_version") != CASE_SCHEMA_VERSION:
        _fail("$.schema_version", f"must be {CASE_SCHEMA_VERSION}")

    hist = _object(raw.get("historicals"), "$.historicals")
    hist_years = hist.get("years")
    if not isinstance(hist_years, list) or not 1 <= len(hist_years) <= 10 or \
            not all(isinstance(y, str) and y for y in hist_years):
        _fail("$.historicals.years", "must list 1-10 fiscal-year labels")
    historicals = {line: _series(hist.get(line), f"$.historicals.{line}", len(hist_years))
                   for line in HISTORICAL_LINES}
    if historicals["revenue"][-1] <= 0:
        _fail("$.historicals.revenue", "latest revenue must be positive")

    bs = _object(raw.get("balance_sheet"), "$.balance_sheet")
    balance_sheet = {key: _number(bs.get(key), f"$.balance_sheet.{key}", low=None if key == "equity" else 0)
                     for key in BALANCE_SHEET_ASSETS + BALANCE_SHEET_CLAIMS}
    gap = sum(balance_sheet[k] for k in BALANCE_SHEET_ASSETS) - sum(balance_sheet[k] for k in BALANCE_SHEET_CLAIMS)
    if abs(gap) > 1e-6:
        _fail("$.balance_sheet", f"assets and claims differ by {gap:.4f}", "BALANCE_SHEET_UNBALANCED")

    market_raw = _object(raw.get("market"), "$.market")
    market = {
        "unaffected_price": _number(market_raw.get("unaffected_price"), "$.market.unaffected_price", positive=True),
        "diluted_shares": _number(market_raw.get("diluted_shares"), "$.market.diluted_shares", positive=True),
        "week52_low": _number(market_raw.get("week52_low"), "$.market.week52_low", positive=True),
        "week52_high": _number(market_raw.get("week52_high"), "$.market.week52_high", positive=True),
    }
    if market["week52_low"] > market["week52_high"]:
        _fail("$.market.week52_low", "must not exceed week52_high")

    proj = _object(raw.get("projection"), "$.projection")
    years = proj.get("years")
    if not isinstance(years, list) or not 3 <= len(years) <= 10 or not all(isinstance(y, str) and y for y in years):
        _fail("$.projection.years", "must list 3-10 fiscal-year labels")
    if set(years) & set(hist_years):
        _fail("$.projection.years", "must not repeat historical years")
    n = len(years)
    projection = {
        "tax_rate": _number(proj.get("tax_rate"), "$.projection.tax_rate", low=0, high=0.6),
        "cash_yield": _number(proj.get("cash_yield", 0.0), "$.projection.cash_yield", low=0, high=0.3),
    }

    scenarios_raw = _object(raw.get("scenarios"), "$.scenarios")
    if "base" not in scenarios_raw:
        _fail("$.scenarios", "needs a base scenario")
    unknown = set(scenarios_raw) - set(SCENARIOS)
    if unknown:
        _fail("$.scenarios", f"unknown scenarios {sorted(unknown)}; use {list(SCENARIOS)}")
    bounds = {"revenue_growth": {"low": -0.9, "high": 2.0}, "gross_margin": {"low": 0, "high": 1},
              "opex_pct": {"low": 0, "high": 1}, "da_pct": {"low": 0, "high": 0.5},
              "capex_pct": {"low": 0, "high": 1}, "receivable_days": {"low": 0, "high": 365},
              "inventory_days": {"low": 0, "high": 365}, "payable_days": {"low": 0, "high": 365}}
    base_raw = _object(scenarios_raw["base"], "$.scenarios.base")
    scenarios = {}
    for name in SCENARIOS:
        if name not in scenarios_raw:
            continue
        spec = _object(scenarios_raw[name], f"$.scenarios.{name}")
        resolved = {}
        for driver in DRIVERS:
            value = spec.get(driver, base_raw.get(driver) if name != "base" else spec.get(driver))
            resolved[driver] = _series(value, f"$.scenarios.{name}.{driver}", n, **bounds[driver])
        resolved["exit_multiple"] = _number(spec.get("exit_multiple", base_raw.get("exit_multiple")),
                                            f"$.scenarios.{name}.exit_multiple", positive=True)
        resolved["probability"] = _number(spec.get("probability", 1.0 if name == "base" else 0.0),
                                          f"$.scenarios.{name}.probability", low=0, high=1)
        scenarios[name] = resolved
    if len(scenarios) > 1 and abs(sum(s["probability"] for s in scenarios.values()) - 1) > 1e-9:
        _fail("$.scenarios", "scenario probabilities must sum to 1")

    tx = _object(raw.get("transaction"), "$.transaction")
    transaction = {
        "offer_premium": _number(tx.get("offer_premium"), "$.transaction.offer_premium", low=0, high=2),
        "transaction_fee_pct": _number(tx.get("transaction_fee_pct"), "$.transaction.transaction_fee_pct",
                                       low=0, high=0.1),
        "financing_fee_pct": _number(tx.get("financing_fee_pct"), "$.transaction.financing_fee_pct", low=0, high=0.1),
        "financing_fee_amortisation_years": _number(tx.get("financing_fee_amortisation_years", n),
                                                    "$.transaction.financing_fee_amortisation_years", positive=True),
        "minimum_cash": _number(tx.get("minimum_cash"), "$.transaction.minimum_cash", low=0),
        "rollover_pct": _number(tx.get("rollover_pct", 0.0), "$.transaction.rollover_pct", low=0, high=0.9),
        "holding_years": int(_number(tx.get("holding_years"), "$.transaction.holding_years", low=1, high=n)),
        "exit_cost_pct": _number(tx.get("exit_cost_pct", 0.0), "$.transaction.exit_cost_pct", low=0, high=0.1),
        "management_incentive_pct": _number(tx.get("management_incentive_pct", 0.0),
                                            "$.transaction.management_incentive_pct", low=0, high=0.5),
        "hurdle_irr": _number(tx.get("hurdle_irr"), "$.transaction.hurdle_irr", low=0, high=1),
        "target_moic": _number(tx.get("target_moic"), "$.transaction.target_moic", positive=True),
        "sweep_pct": _number(tx.get("sweep_pct", 1.0), "$.transaction.sweep_pct", low=0, high=1),
    }
    if transaction["holding_years"] != _number(tx.get("holding_years"), "$.transaction.holding_years"):
        _fail("$.transaction.holding_years", "must be a whole number of years")

    debt_raw = raw.get("debt")
    if not isinstance(debt_raw, list) or not 1 <= len(debt_raw) <= 4:
        _fail("$.debt", "must list 1-4 tranches")
    tranches = []
    for index, item in enumerate(debt_raw):
        path = f"$.debt[{index}]"
        item = _object(item, path)
        kind = item.get("kind")
        if kind not in {"amortizing", "bullet"}:
            _fail(f"{path}.kind", "must be amortizing or bullet")
        amortization = _series(item.get("amortization", [0] * n), f"{path}.amortization", n, low=0, high=1)
        if sum(amortization) > 1 + 1e-9:
            _fail(f"{path}.amortization", "scheduled repayments exceed the principal")
        if kind == "bullet" and any(amortization):
            _fail(f"{path}.amortization", "a bullet tranche has no scheduled amortization")
        for flag in ("sweep", "subject_to_interest_cap"):
            if not isinstance(item.get(flag, False), bool):
                _fail(f"{path}.{flag}", "must be true or false")
        tranches.append(Tranche(
            name=_text(item.get("name"), f"{path}.name"), kind=kind,
            ebitda_multiple=_number(item.get("ebitda_multiple"), f"{path}.ebitda_multiple", low=0, high=10),
            cash_rate=_number(item.get("cash_rate"), f"{path}.cash_rate", low=0, high=0.5),
            pik_rate=_number(item.get("pik_rate", 0.0), f"{path}.pik_rate", low=0, high=0.5),
            amortization=tuple(amortization), sweep=item.get("sweep", False),
            subject_to_interest_cap=item.get("subject_to_interest_cap", False)))

    rv = _object(raw.get("revolver"), "$.revolver")
    revolver = {"commitment": _number(rv.get("commitment"), "$.revolver.commitment", low=0),
                "cash_rate": _number(rv.get("cash_rate"), "$.revolver.cash_rate", low=0, high=0.5),
                "undrawn_fee": _number(rv.get("undrawn_fee", 0.0), "$.revolver.undrawn_fee", low=0, high=0.05)}

    cv = _object(raw.get("covenants"), "$.covenants")
    covenants = {"max_net_leverage": _series(cv.get("max_net_leverage"), "$.covenants.max_net_leverage", n,
                                             positive=True),
                 "min_interest_cover": _number(cv.get("min_interest_cover"), "$.covenants.min_interest_cover",
                                               positive=True),
                 "min_dscr": _number(cv.get("min_dscr"), "$.covenants.min_dscr", positive=True)}

    tx_tax = _object(raw.get("tax", {}), "$.tax")
    tax = {"interest_cap_pct_ebitda": _number(tx_tax.get("interest_cap_pct_ebitda", 0.3),
                                              "$.tax.interest_cap_pct_ebitda", low=0, high=1),
           "interest_cap_threshold": _number(tx_tax.get("interest_cap_threshold", 1.0),
                                             "$.tax.interest_cap_threshold", low=0)}

    val = _object(raw.get("valuation"), "$.valuation")
    peers = val.get("peer_betas")
    if not isinstance(peers, list) or not peers:
        _fail("$.valuation.peer_betas", "must list at least one peer")
    valuation = {
        "risk_free": _number(val.get("risk_free"), "$.valuation.risk_free", low=0, high=0.3),
        "equity_risk_premium": _number(val.get("equity_risk_premium"), "$.valuation.equity_risk_premium",
                                       low=0, high=0.3),
        "size_premium": _number(val.get("size_premium", 0.0), "$.valuation.size_premium", low=0, high=0.2),
        "pre_tax_cost_of_debt": _number(val.get("pre_tax_cost_of_debt"), "$.valuation.pre_tax_cost_of_debt",
                                        low=0, high=0.5),
        "target_debt_to_capital": _number(val.get("target_debt_to_capital"), "$.valuation.target_debt_to_capital",
                                          low=0, high=0.9),
        "terminal_growth": _number(val.get("terminal_growth"), "$.valuation.terminal_growth", low=-0.05, high=0.15),
        "exit_multiple": _number(val.get("exit_multiple"), "$.valuation.exit_multiple", positive=True),
        "mid_year": val.get("mid_year", True),
        "peer_betas": tuple({
            "name": _text(p.get("name"), f"$.valuation.peer_betas[{i}].name"),
            "levered_beta": _number(p.get("levered_beta"), f"$.valuation.peer_betas[{i}].levered_beta", positive=True),
            "debt_to_equity": _number(p.get("debt_to_equity"), f"$.valuation.peer_betas[{i}].debt_to_equity", low=0),
            "tax_rate": _number(p.get("tax_rate"), f"$.valuation.peer_betas[{i}].tax_rate", low=0, high=0.6),
        } for i, p in enumerate([_object(p, f"$.valuation.peer_betas[{i}]") for i, p in enumerate(peers)])),
    }
    if not isinstance(valuation["mid_year"], bool):
        _fail("$.valuation.mid_year", "must be true or false")

    comps_raw = raw.get("comps")
    if not isinstance(comps_raw, list) or len(comps_raw) < 3:
        _fail("$.comps", "must list at least three trading comparables")
    comps = []
    for i, c in enumerate(comps_raw):
        c = _object(c, f"$.comps[{i}]")
        comps.append({
            "name": _text(c.get("name"), f"$.comps[{i}].name"),
            "market_cap": _number(c.get("market_cap"), f"$.comps[{i}].market_cap", positive=True),
            "net_debt": _number(c.get("net_debt"), f"$.comps[{i}].net_debt"),
            "revenue": _number(c.get("revenue"), f"$.comps[{i}].revenue", positive=True),
            "ebitda": _number(c.get("ebitda"), f"$.comps[{i}].ebitda", positive=True),
            "net_income": _number(c.get("net_income"), f"$.comps[{i}].net_income", positive=True),
            "revenue_growth": _number(c.get("revenue_growth", 0.0), f"$.comps[{i}].revenue_growth"),
            "ebitda_margin": _number(c.get("ebitda_margin", c.get("ebitda", 0) / c.get("revenue", 1)),
                                     f"$.comps[{i}].ebitda_margin"),
        })
    precedents_raw = raw.get("precedents")
    if not isinstance(precedents_raw, list) or len(precedents_raw) < 3:
        _fail("$.precedents", "must list at least three precedent transactions")
    precedents = []
    for i, p in enumerate(precedents_raw):
        p = _object(p, f"$.precedents[{i}]")
        precedents.append({
            "target": _text(p.get("target"), f"$.precedents[{i}].target"),
            "acquirer": _text(p.get("acquirer"), f"$.precedents[{i}].acquirer"),
            "year": _text(p.get("year"), f"$.precedents[{i}].year"),
            "ev_ebitda": _number(p.get("ev_ebitda"), f"$.precedents[{i}].ev_ebitda", positive=True),
            "premium": _number(p.get("premium"), f"$.precedents[{i}].premium", low=-0.5, high=3),
        })

    mc = _object(raw.get("monte_carlo", {}), "$.monte_carlo")
    base_exit = scenarios["base"]["exit_multiple"]
    monte_carlo = {
        "paths": int(_number(mc.get("paths", 1000), "$.monte_carlo.paths", low=0, high=100000)),
        "seed": int(_number(mc.get("seed", 7), "$.monte_carlo.seed")),
        "revenue_growth_sd": _number(mc.get("revenue_growth_sd", 0.02), "$.monte_carlo.revenue_growth_sd", low=0),
        "ebitda_margin_sd": _number(mc.get("ebitda_margin_sd", 0.01), "$.monte_carlo.ebitda_margin_sd", low=0),
        "exit_multiple_low": _number(mc.get("exit_multiple_low", base_exit * 0.75), "$.monte_carlo.exit_multiple_low",
                                     positive=True),
        "exit_multiple_mode": _number(mc.get("exit_multiple_mode", base_exit), "$.monte_carlo.exit_multiple_mode",
                                      positive=True),
        "exit_multiple_high": _number(mc.get("exit_multiple_high", base_exit * 1.2),
                                      "$.monte_carlo.exit_multiple_high", positive=True),
    }
    if not monte_carlo["exit_multiple_low"] <= monte_carlo["exit_multiple_mode"] <= monte_carlo["exit_multiple_high"]:
        _fail("$.monte_carlo", "exit multiples must satisfy low <= mode <= high")

    illustrative = raw.get("illustrative", False)
    if not isinstance(illustrative, bool):
        _fail("$.illustrative", "must be true or false")
    return DealCase(
        raw=raw, name=_text(raw.get("name"), "$.name"), company=_text(raw.get("company"), "$.company"),
        illustrative=illustrative, historical_years=tuple(hist_years), projection_years=tuple(years),
        historicals=historicals, balance_sheet=balance_sheet, market=market, projection=projection,
        scenarios=scenarios, transaction=transaction, tranches=tuple(tranches), revolver=revolver,
        covenants=covenants, tax=tax, valuation=valuation, comps=tuple(comps), precedents=tuple(precedents),
        monte_carlo=monte_carlo)
