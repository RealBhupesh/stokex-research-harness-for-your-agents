"""Standalone valuation: WACC build-up, unlevered DCF, trading comparables and precedent transactions."""

from .statements import operating_plan


def median(values: list[float]) -> float:
    return quartile(values, 2)


def quartile(values: list[float], q: int) -> float:
    """Excel QUARTILE.INC: linear interpolation at (n - 1) * q / 4."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 4
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summary(values: list[float]) -> dict:
    return {"min": min(values), "q1": quartile(values, 1), "median": quartile(values, 2),
            "mean": sum(values) / len(values), "q3": quartile(values, 3), "max": max(values)}


def wacc(case, *, wacc_override: float | None = None) -> dict:
    v, tax_rate = case.valuation, case.projection["tax_rate"]
    peers = []
    for peer in v["peer_betas"]:
        unlevered = peer["levered_beta"] / (1 + (1 - peer["tax_rate"]) * peer["debt_to_equity"])
        peers.append({**peer, "unlevered_beta": unlevered})
    unlevered_beta = median([p["unlevered_beta"] for p in peers])
    weight_debt = v["target_debt_to_capital"]
    debt_to_equity = weight_debt / (1 - weight_debt)
    relevered = unlevered_beta * (1 + (1 - tax_rate) * debt_to_equity)
    cost_of_equity = v["risk_free"] + relevered * v["equity_risk_premium"] + v["size_premium"]
    after_tax_debt = v["pre_tax_cost_of_debt"] * (1 - tax_rate)
    rate = (1 - weight_debt) * cost_of_equity + weight_debt * after_tax_debt
    return {"peers": peers, "unlevered_beta": unlevered_beta, "target_debt_to_equity": debt_to_equity,
            "relevered_beta": relevered, "cost_of_equity": cost_of_equity, "after_tax_cost_of_debt": after_tax_debt,
            "weight_debt": weight_debt, "weight_equity": 1 - weight_debt,
            "wacc": rate if wacc_override is None else wacc_override}


def standalone_net_debt(case) -> float:
    return case.balance_sheet["debt"] - case.balance_sheet["cash"]


def dcf(case, scenario: str = "base", *, discount_rate: float | None = None, terminal_growth: float | None = None,
        exit_multiple: float | None = None) -> dict:
    v = case.valuation
    plan = operating_plan(case, case.drivers(scenario))
    rate = wacc(case)["wacc"] if discount_rate is None else discount_rate
    growth = v["terminal_growth"] if terminal_growth is None else terminal_growth
    multiple = v["exit_multiple"] if exit_multiple is None else exit_multiple
    if rate <= growth:
        raise ValueError("discount rate must exceed terminal growth")
    n, shift = case.years, 0.5 if v["mid_year"] else 0.0
    periods = [t + 1 - shift for t in range(n)]
    factors = [(1 + rate) ** -p for p in periods]
    pv_flows = [f * d for f, d in zip(plan["fcff"], factors)]
    fcff_n, ebitda_n = plan["fcff"][-1], plan["ebitda"][-1]
    # A Gordon value of mid-year flows sits half a year before year end, hence the shorter discount period.
    gordon_tv = fcff_n * (1 + growth) / (rate - growth)
    gordon_pv = gordon_tv * (1 + rate) ** -(n - shift)
    exit_tv = multiple * ebitda_n
    exit_pv = exit_tv * (1 + rate) ** -n
    adjust = (1 + rate) ** shift
    implied_multiple = gordon_tv * adjust / ebitda_n
    k = exit_tv / adjust
    implied_growth = (k * rate - fcff_n) / (k + fcff_n)
    net_debt = standalone_net_debt(case)
    shares = case.market["diluted_shares"]

    def bridge(tv_pv):
        ev = sum(pv_flows) + tv_pv
        equity = ev - net_debt
        return {"enterprise_value": ev, "equity_value": equity, "value_per_share": equity / shares,
                "terminal_share": tv_pv / ev, "implied_ev_ebitda_ltm": ev / case.ltm_ebitda}

    return {"scenario": scenario, "wacc": rate, "terminal_growth": growth, "exit_multiple": multiple,
            "periods": periods, "discount_factors": factors, "fcff": plan["fcff"], "pv_fcff": pv_flows,
            "sum_pv_fcff": sum(pv_flows), "gordon_terminal_value": gordon_tv, "gordon_terminal_pv": gordon_pv,
            "exit_terminal_value": exit_tv, "exit_terminal_pv": exit_pv, "implied_exit_multiple": implied_multiple,
            "implied_terminal_growth": implied_growth, "net_debt": net_debt, "plan": plan,
            "gordon": bridge(gordon_pv), "exit": bridge(exit_pv)}


def standalone_ntm_net_income(case, plan: dict) -> float:
    h = case.historicals
    return (plan["ebit"][0] - h["finance_cost"][-1] + h["other_income"][-1]) * (1 - case.projection["tax_rate"])


def trading_comps(case) -> dict:
    plan = operating_plan(case, case.drivers("base"))
    rows = []
    for comp in case.comps:
        ev = comp["market_cap"] + comp["net_debt"]
        rows.append({**comp, "enterprise_value": ev, "ev_revenue": ev / comp["revenue"],
                     "ev_ebitda": ev / comp["ebitda"], "pe": comp["market_cap"] / comp["net_income"]})
    stats = {key: summary([r[key] for r in rows]) for key in ("ev_revenue", "ev_ebitda", "pe", "revenue_growth",
                                                              "ebitda_margin")}
    net_debt, shares = standalone_net_debt(case), case.market["diluted_shares"]
    metrics = {"revenue": plan["revenue"][0], "ebitda": plan["ebitda"][0],
               "net_income": standalone_ntm_net_income(case, plan)}
    implied = {}
    for key, metric, enterprise in (("ev_revenue", "revenue", True), ("ev_ebitda", "ebitda", True),
                                    ("pe", "net_income", False)):
        implied[key] = {}
        for point in ("q1", "median", "q3"):
            value = stats[key][point] * metrics[metric]
            equity = value - net_debt if enterprise else value
            implied[key][point] = equity / shares
    unaffected_mcap = case.market["unaffected_price"] * shares
    target = {"ev_revenue": (unaffected_mcap + net_debt) / metrics["revenue"],
              "ev_ebitda": (unaffected_mcap + net_debt) / metrics["ebitda"],
              "pe": unaffected_mcap / metrics["net_income"]}
    return {"rows": rows, "stats": stats, "target_metrics": metrics, "target_multiples": target,
            "implied_price": implied, "basis": f"NTM ({case.projection_years[0]}E)"}


def precedent_transactions(case) -> dict:
    rows = list(case.precedents)
    stats = {"ev_ebitda": summary([r["ev_ebitda"] for r in rows]), "premium": summary([r["premium"] for r in rows])}
    net_debt, shares = standalone_net_debt(case), case.market["diluted_shares"]
    implied = {"ev_ebitda": {}, "premium": {}}
    for point in ("q1", "median", "q3"):
        implied["ev_ebitda"][point] = (stats["ev_ebitda"][point] * case.ltm_ebitda - net_debt) / shares
        implied["premium"][point] = case.market["unaffected_price"] * (1 + stats["premium"][point])
    return {"rows": rows, "stats": stats, "implied_price": implied, "basis": f"LTM ({case.historical_years[-1]}A)"}
