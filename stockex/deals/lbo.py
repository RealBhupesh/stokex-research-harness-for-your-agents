"""Leveraged buyout: sources and uses, pro forma balance sheet, covenants, returns and the value-creation bridge."""

from .case import DealCaseError
from .statements import financed_statements, operating_plan


def irr(cash_flows: list[float], *, low: float = -0.9999, high: float = 10.0, tolerance: float = 1e-12) -> float | None:
    """Annual IRR by bisection. Returns None when NPV does not change sign in [low, high]."""
    def npv(rate):
        return sum(flow / (1 + rate) ** t for t, flow in enumerate(cash_flows))
    f_low, f_high = npv(low), npv(high)
    if f_low == 0:
        return low
    if f_low * f_high > 0:
        return None
    for _ in range(300):
        mid = (low + high) / 2
        f_mid = npv(mid)
        if abs(f_mid) < tolerance or high - low < tolerance:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def offer_price(case) -> float:
    return case.market["unaffected_price"] * (1 + case.transaction["offer_premium"])


def sources_and_uses(case, *, price: float | None = None, leverage_scale: float = 1.0, validate: bool = True) -> dict:
    """Sources equal uses by construction: sponsor equity is the plug (it must be positive when ``validate``)."""
    price = offer_price(case) if price is None else price
    bs, tx = case.balance_sheet, case.transaction
    ltm_ebitda = case.ltm_ebitda
    equity_purchase = price * case.market["diluted_shares"]
    entry_ev = equity_purchase + bs["debt"] - bs["cash"]
    tranches = [{"name": t.name, "principal": t.ebitda_multiple * leverage_scale * ltm_ebitda,
                 "cash_rate": t.cash_rate, "pik_rate": t.pik_rate, "amortization": t.amortization,
                 "sweep": t.sweep, "subject_to_interest_cap": t.subject_to_interest_cap, "kind": t.kind}
                for t in case.tranches]
    new_debt = sum(t["principal"] for t in tranches)
    transaction_fees = tx["transaction_fee_pct"] * entry_ev
    financing_fees = tx["financing_fee_pct"] * new_debt
    existing_cash_used = bs["cash"] - tx["minimum_cash"]
    rollover = tx["rollover_pct"] * equity_purchase
    uses = {"equity_purchase": equity_purchase, "refinance_existing_debt": bs["debt"],
            "transaction_fees": transaction_fees, "financing_fees": financing_fees}
    sponsor_equity = sum(uses.values()) - new_debt - rollover - existing_cash_used
    if validate and sponsor_equity <= 0:
        raise DealCaseError("EQUITY_CHEQUE_NOT_POSITIVE",
                            f"debt, rollover and existing cash cover all uses at a price of {price:.2f}; "
                            "reduce leverage or raise the price", "$.debt")
    sources = {**{t["name"]: t["principal"] for t in tranches}, "existing_cash_used": existing_cash_used,
               "rollover_equity": rollover, "sponsor_equity": sponsor_equity}
    return {
        "offer_price": price, "premium": price / case.market["unaffected_price"] - 1,
        "equity_purchase": equity_purchase, "entry_ev": entry_ev, "ltm_ebitda": ltm_ebitda,
        "entry_multiple": entry_ev / ltm_ebitda, "new_debt": new_debt, "leverage": new_debt / ltm_ebitda,
        "net_debt_at_close": new_debt - tx["minimum_cash"], "sponsor_equity": sponsor_equity,
        "rollover_equity": rollover, "total_equity": sponsor_equity + rollover,
        "equity_contribution": (sponsor_equity + rollover) / (sponsor_equity + rollover + new_debt),
        "transaction_fees": transaction_fees, "financing_fees": financing_fees,
        "sources": sources, "uses": uses, "total_sources": sum(sources.values()), "total_uses": sum(uses.values()),
        "tranches": tranches,
    }


def pro_forma_balance_sheet(case, su: dict) -> dict:
    """Closing balance sheet after the deal. Goodwill is the purchase price over book equity (no PPA write-ups)."""
    bs = case.balance_sheet
    goodwill = su["equity_purchase"] - bs["equity"]
    opening = {
        "cash": case.transaction["minimum_cash"], "receivables": bs["receivables"], "inventory": bs["inventory"],
        "other_current_assets": bs["other_current_assets"], "ppe": bs["ppe"], "intangibles": bs["intangibles"],
        "goodwill": goodwill, "other_non_current_assets": bs["other_non_current_assets"],
        "deferred_financing_fees": su["financing_fees"], "payables": bs["payables"],
        "other_current_liabilities": bs["other_current_liabilities"], "revolver": 0.0,
        "debt": su["new_debt"], "other_non_current_liabilities": bs["other_non_current_liabilities"],
        "equity": su["total_equity"] - su["transaction_fees"],
    }
    assets = sum(opening[k] for k in ("cash", "receivables", "inventory", "other_current_assets", "ppe",
                                      "intangibles", "goodwill", "other_non_current_assets",
                                      "deferred_financing_fees"))
    claims = sum(opening[k] for k in ("payables", "other_current_liabilities", "revolver", "debt",
                                      "other_non_current_liabilities", "equity"))
    opening.update(total_assets=assets, total_claims=claims, balance_check=assets - claims)
    return opening


def covenant_tests(case, plan: dict, fin: dict) -> dict:
    cov = case.covenants
    rows = {"net_leverage": [], "interest_cover": [], "dscr": [], "leverage_headroom": [], "icr_headroom": [],
            "dscr_headroom": [], "ebitda_cushion": [], "breaches": []}
    first_breach = None
    for i in range(case.years):
        ebitda = plan["ebitda"][i]
        cash_interest = fin["cash_interest"][i] + fin["revolver_interest"][i] + fin["undrawn_fee"][i]
        debt_service = cash_interest + fin["mandatory"][i]
        leverage = fin["net_debt"][i] / ebitda
        icr = ebitda / cash_interest if cash_interest > 0 else None
        dscr = (ebitda - plan["capex"][i] - fin["tax"][i]) / debt_service if debt_service > 0 else None
        # EBITDA cushion: share of EBITDA that could disappear (debt, interest, capex and tax held) before a breach.
        cushions = [1 - fin["net_debt"][i] / (cov["max_net_leverage"][i] * ebitda),
                    1 - cov["min_interest_cover"] * cash_interest / ebitda,
                    1 - (cov["min_dscr"] * debt_service + plan["capex"][i] + fin["tax"][i]) / ebitda]
        breaches = []
        if leverage > cov["max_net_leverage"][i] + 1e-12:
            breaches.append("NET_LEVERAGE")
        if icr is not None and icr < cov["min_interest_cover"] - 1e-12:
            breaches.append("INTEREST_COVER")
        if dscr is not None and dscr < cov["min_dscr"] - 1e-12:
            breaches.append("DSCR")
        if fin["liquidity_shortfall"][i]:
            breaches.append("LIQUIDITY")
        if breaches and first_breach is None:
            first_breach = {"year": case.projection_years[i], "index": i, "tests": breaches}
        rows["net_leverage"].append(leverage)
        rows["interest_cover"].append(icr)
        rows["dscr"].append(dscr)
        rows["leverage_headroom"].append(cov["max_net_leverage"][i] - leverage)
        rows["icr_headroom"].append(None if icr is None else icr - cov["min_interest_cover"])
        rows["dscr_headroom"].append(None if dscr is None else dscr - cov["min_dscr"])
        rows["ebitda_cushion"].append(min(cushions))
        rows["breaches"].append(breaches)
    rows["first_breach"] = first_breach
    rows["minimum_ebitda_cushion"] = min(rows["ebitda_cushion"])
    return rows


def returns(case, su: dict, plan: dict, fin: dict, *, exit_multiple: float, holding_years: int) -> dict:
    tx = case.transaction
    i = holding_years - 1
    exit_ebitda = plan["ebitda"][i]
    exit_ev = exit_multiple * exit_ebitda
    exit_costs = tx["exit_cost_pct"] * exit_ev
    exit_net_debt = fin["net_debt"][i]
    exit_equity = exit_ev - exit_costs - exit_net_debt
    invested = su["total_equity"]
    incentive = tx["management_incentive_pct"] * max(0.0, exit_equity - invested)
    sponsor_share = su["sponsor_equity"] / invested
    sponsor_proceeds = max(0.0, exit_equity - incentive) * sponsor_share
    flows = [-su["sponsor_equity"]] + [0.0] * (holding_years - 1) + [sponsor_proceeds]
    sponsor_irr = irr(flows) if sponsor_proceeds > 0 else -1.0
    moic = sponsor_proceeds / su["sponsor_equity"]
    bridge = {
        "ebitda_growth": (exit_ebitda - su["ltm_ebitda"]) * su["entry_multiple"],
        "multiple_change": (exit_multiple - su["entry_multiple"]) * exit_ebitda,
        "deleveraging": su["net_debt_at_close"] - exit_net_debt,
        "fees_and_costs": -(su["transaction_fees"] + su["financing_fees"] + exit_costs),
    }
    bridge["total_equity_gain"] = sum(bridge.values())
    bridge["bridge_check"] = bridge["total_equity_gain"] - (exit_equity - invested)
    return {
        "exit_year": case.projection_years[i], "holding_years": holding_years, "exit_multiple": exit_multiple,
        "exit_ebitda": exit_ebitda, "exit_ev": exit_ev, "exit_costs": exit_costs, "exit_net_debt": exit_net_debt,
        "exit_equity": exit_equity, "management_incentive": incentive, "sponsor_share": sponsor_share,
        "sponsor_proceeds": sponsor_proceeds, "rollover_proceeds": max(0.0, exit_equity - incentive) - sponsor_proceeds,
        "cash_flows": flows, "irr": sponsor_irr, "moic": moic, "bridge": bridge,
    }


def run_lbo(case, scenario: str = "base", *, price: float | None = None, exit_multiple: float | None = None,
            holding_years: int | None = None, leverage_scale: float = 1.0, growth_shift: float = 0.0,
            margin_shift: float = 0.0, ebitda_haircut: float = 0.0) -> dict:
    """Run one complete LBO case; keyword overrides support sensitivities and solvers."""
    drivers = case.drivers(scenario)
    plan = operating_plan(case, drivers, growth_shift=growth_shift, margin_shift=margin_shift,
                          ebitda_haircut=ebitda_haircut)
    su = sources_and_uses(case, price=price, leverage_scale=leverage_scale)
    opening = pro_forma_balance_sheet(case, su)
    fin = financed_statements(case, plan, opening, su["tranches"])
    covenants = covenant_tests(case, plan, fin)
    exit_multiple = drivers["exit_multiple"] if exit_multiple is None else exit_multiple
    holding = case.transaction["holding_years"] if holding_years is None else holding_years
    result = returns(case, su, plan, fin, exit_multiple=exit_multiple, holding_years=holding)
    by_year = [returns(case, su, plan, fin, exit_multiple=exit_multiple, holding_years=y)
               for y in range(1, case.years + 1)]
    checks = {
        "sources_minus_uses": su["total_sources"] - su["total_uses"],
        "pro_forma_balance": opening["balance_check"],
        "max_balance_error": max(abs(x) for x in fin["balance_check"]),
        "max_cash_error": max(abs(x) for x in fin["cash_check"]),
        "bridge_error": result["bridge"]["bridge_check"],
    }
    checks["ok"] = all(abs(v) < 1e-6 for v in checks.values())
    return {"scenario": scenario, "drivers": drivers, "plan": plan, "sources_uses": su, "pro_forma": opening,
            "statements": fin, "covenants": covenants, "returns": result,
            "returns_by_exit_year": [{"exit_year": r["exit_year"], "irr": r["irr"], "moic": r["moic"]}
                                     for r in by_year],
            "checks": checks}
