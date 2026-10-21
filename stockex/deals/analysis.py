"""Deal analysis: scenarios, sensitivities, breakeven solvers, Monte Carlo, the football field and the bid."""

import random

from .case import DealCaseError
from .lbo import run_lbo, sources_and_uses
from .valuation import dcf, precedent_transactions, quartile, trading_comps, wacc


def solve(function, target: float, low: float, high: float, *, iterations: int = 200,
          tolerance: float = 1e-9) -> float | None:
    """Find x in [low, high] with function(x) = target for a monotonic function, or None if not bracketed."""
    f_low, f_high = function(low) - target, function(high) - target
    if f_low == 0:
        return low
    if f_high == 0:
        return high
    if f_low * f_high > 0:
        return None
    for _ in range(iterations):
        mid = (low + high) / 2
        f_mid = function(mid) - target
        if abs(f_mid) < tolerance or high - low < tolerance:
            return mid
        if f_low * f_mid < 0:
            high = mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def price_for_multiple(case, multiple: float) -> float:
    bs = case.balance_sheet
    return (multiple * case.ltm_ebitda - bs["debt"] + bs["cash"]) / case.market["diluted_shares"]


def _smallest_true(predicate, low: float, high: float, *, iterations: int = 60) -> float | None:
    """Smallest x in [low, high] where a monotonic predicate turns true."""
    if predicate(low):
        return low
    if not predicate(high):
        return None
    for _ in range(iterations):
        mid = (low + high) / 2
        if predicate(mid):
            high = mid
        else:
            low = mid
    return high


def scenario_table(case) -> dict:
    rows = {}
    for name in case.scenarios:
        result = run_lbo(case, name)
        r, cov = result["returns"], result["covenants"]
        rows[name] = {"probability": case.scenarios[name]["probability"], "irr": r["irr"], "moic": r["moic"],
                      "exit_multiple": r["exit_multiple"], "exit_ebitda": r["exit_ebitda"],
                      "exit_equity": r["exit_equity"], "sponsor_proceeds": r["sponsor_proceeds"],
                      "revenue_cagr": (result["plan"]["revenue"][r["holding_years"] - 1]
                                       / case.historicals["revenue"][-1]) ** (1 / r["holding_years"]) - 1,
                      "exit_ebitda_margin": result["plan"]["ebitda_margin"][r["holding_years"] - 1],
                      "first_breach": cov["first_breach"], "minimum_ebitda_cushion": cov["minimum_ebitda_cushion"],
                      "peak_net_leverage": max(cov["net_leverage"])}
    weighted = None
    if len(rows) > 1:
        weighted = {"moic": sum(r["probability"] * r["moic"] for r in rows.values()),
                    "irr": sum(r["probability"] * r["irr"] for r in rows.values()),
                    "proceeds": sum(r["probability"] * r["sponsor_proceeds"] for r in rows.values())}
    return {"rows": rows, "probability_weighted": weighted}


def sensitivities(case) -> dict:
    base = run_lbo(case)
    entry = base["sources_uses"]["entry_multiple"]
    exit_ = base["returns"]["exit_multiple"]
    entry_axis = [entry + step for step in (-2, -1, 0, 1, 2)]
    exit_axis = [exit_ + step for step in (-2, -1, 0, 1, 2)]
    leverage_axis = [3.0, 3.5, 4.0, 4.5, 5.0]
    growth_axis = [-0.04, -0.02, 0.0, 0.02, 0.04]
    margin_axis = [-0.02, -0.01, 0.0, 0.01, 0.02]
    base_leverage = base["sources_uses"]["leverage"]

    def cell(fn, r, c):
        try:
            return fn(r, c)
        except DealCaseError:   # infeasible corner, e.g. debt alone would fund the deal
            return None

    def grid(rows, cols, fn):
        return [[cell(fn, r, c) for c in cols] for r in rows]

    def lbo(**kw):
        return run_lbo(case, **kw)["returns"]

    irr_entry_exit = grid(entry_axis, exit_axis, lambda m, x: lbo(price=price_for_multiple(case, m),
                                                                  exit_multiple=x)["irr"])
    moic_entry_exit = grid(entry_axis, exit_axis, lambda m, x: lbo(price=price_for_multiple(case, m),
                                                                   exit_multiple=x)["moic"])
    irr_leverage_exit = grid(leverage_axis, exit_axis, lambda lev, x: lbo(leverage_scale=lev / base_leverage,
                                                                          exit_multiple=x)["irr"])
    irr_growth_margin = grid(growth_axis, margin_axis, lambda g, m: lbo(growth_shift=g, margin_shift=m)["irr"])
    w = wacc(case)["wacc"]
    g = case.valuation["terminal_growth"]
    wacc_axis = [w + step for step in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    growth_tv_axis = [g + step for step in (-0.01, -0.005, 0.0, 0.005, 0.01)]
    dcf_grid = grid(wacc_axis, growth_tv_axis,
                    lambda r, tg: dcf(case, discount_rate=r, terminal_growth=tg)["gordon"]["value_per_share"])
    return {
        "irr_entry_exit": {"rows": entry_axis, "cols": exit_axis, "values": irr_entry_exit,
                           "row_label": "Entry EV / LTM EBITDA", "col_label": "Exit EV / EBITDA"},
        "moic_entry_exit": {"rows": entry_axis, "cols": exit_axis, "values": moic_entry_exit,
                            "row_label": "Entry EV / LTM EBITDA", "col_label": "Exit EV / EBITDA"},
        "irr_leverage_exit": {"rows": leverage_axis, "cols": exit_axis, "values": irr_leverage_exit,
                              "row_label": "Total debt / LTM EBITDA", "col_label": "Exit EV / EBITDA"},
        "irr_growth_margin": {"rows": growth_axis, "cols": margin_axis, "values": irr_growth_margin,
                              "row_label": "Revenue growth shift (every year)",
                              "col_label": "EBITDA margin shift (every year)"},
        "dcf_wacc_growth": {"rows": wacc_axis, "cols": growth_tv_axis, "values": dcf_grid,
                            "row_label": "WACC", "col_label": "Terminal growth"},
    }


def breakevens(case) -> dict:
    tx = case.transaction
    base = run_lbo(case)
    holding = base["returns"]["holding_years"]

    def exit_for(metric, target):
        return solve(lambda m: run_lbo(case, exit_multiple=m)["returns"][metric], target, 0.5, 60.0)

    unaffected = case.market["unaffected_price"]
    # Below this price the debt alone would fund the deal; keep at least a 10% equity cheque.
    floor = solve(lambda p: sources_and_uses(case, price=p, validate=False)["equity_contribution"], 0.10, 0.01, 10 * unaffected)
    floor = max(floor or 0.0, 0.2 * unaffected)

    def price_for(scenario, metric, target):
        return solve(lambda p: run_lbo(case, scenario, price=p)["returns"][metric], target, floor, 5.0 * unaffected)

    covenant_haircut = _smallest_true(lambda h: run_lbo(case, ebitda_haircut=h)["covenants"]["first_breach"]
                                      is not None, 0.0, 0.95)
    wipeout_haircut = solve(lambda h: run_lbo(case, ebitda_haircut=h)["returns"]["moic"], 1.0, 0.0, 0.95)
    liquidity_haircut = _smallest_true(lambda h: any(run_lbo(case, ebitda_haircut=h)["statements"]
                                                     ["liquidity_shortfall"]), 0.0, 0.95)
    hurdle_price = price_for("base", "irr", tx["hurdle_irr"])
    stretch_price = price_for("base", "irr", tx["hurdle_irr"] + 0.05)
    downside = "downside" if "downside" in case.scenarios else "base"
    preservation_price = price_for(downside, "moic", 1.0)
    candidates = [p for p in (hurdle_price, preservation_price) if p is not None]
    max_bid = min(candidates) if candidates else None
    return {
        "holding_years": holding,
        "exit_multiple_for_1x": exit_for("moic", 1.0),
        "exit_multiple_for_2x": exit_for("moic", 2.0),
        "exit_multiple_for_target_moic": exit_for("moic", tx["target_moic"]),
        "exit_multiple_for_hurdle_irr": exit_for("irr", tx["hurdle_irr"]),
        "ebitda_haircut_to_covenant_breach": covenant_haircut,
        "ebitda_haircut_to_liquidity_shortfall": liquidity_haircut,
        "ebitda_haircut_to_1x": wipeout_haircut,
        "price_at_hurdle_irr": hurdle_price,
        "price_at_hurdle_plus_5": stretch_price,
        "price_at_downside_1x": preservation_price,
        "max_bid": max_bid,
        "max_bid_binding_constraint": None if max_bid is None else (
            "base-case hurdle IRR" if max_bid == hurdle_price else f"{downside}-case capital preservation (1.0x)"),
        "offer_price": base["sources_uses"]["offer_price"],
        "headroom_to_max_bid": None if max_bid is None else max_bid / base["sources_uses"]["offer_price"] - 1,
    }


def _percentile(values: list[float], p: float) -> float:
    return quartile(values, 4 * p)


def monte_carlo(case) -> dict:
    mc = case.monte_carlo
    if mc["paths"] == 0:
        return {"paths": 0}
    rng = random.Random(mc["seed"])
    irrs, moics, breaches = [], [], 0
    for _ in range(mc["paths"]):
        growth = rng.gauss(0.0, mc["revenue_growth_sd"])
        margin = rng.gauss(0.0, mc["ebitda_margin_sd"])
        multiple = rng.triangular(mc["exit_multiple_low"], mc["exit_multiple_high"], mc["exit_multiple_mode"])
        result = run_lbo(case, growth_shift=growth, margin_shift=margin, exit_multiple=multiple)
        irrs.append(result["returns"]["irr"])
        moics.append(result["returns"]["moic"])
        breaches += result["covenants"]["first_breach"] is not None
    tx, n = case.transaction, len(irrs)
    return {
        "paths": n, "seed": mc["seed"],
        "assumptions": {k: v for k, v in mc.items() if k not in {"paths", "seed"}},
        "irr": {"p5": _percentile(irrs, 0.05), "p25": _percentile(irrs, 0.25), "p50": _percentile(irrs, 0.5),
                "p75": _percentile(irrs, 0.75), "p95": _percentile(irrs, 0.95), "mean": sum(irrs) / n},
        "moic": {"p5": _percentile(moics, 0.05), "p50": _percentile(moics, 0.5), "p95": _percentile(moics, 0.95),
                 "mean": sum(moics) / n},
        "probability_loss": sum(m < 1.0 for m in moics) / n,
        "probability_hurdle": sum(r >= tx["hurdle_irr"] for r in irrs) / n,
        "probability_target_moic": sum(m >= tx["target_moic"] for m in moics) / n,
        "probability_covenant_breach": breaches / n,
        "histogram": _histogram(irrs),
    }


def _histogram(values: list[float], *, low: float = -0.2, high: float = 0.5, buckets: int = 14) -> list[dict]:
    width = (high - low) / buckets
    counts = [0] * buckets
    for value in values:
        index = min(buckets - 1, max(0, int((value - low) / width)))
        counts[index] += 1
    return [{"from": low + i * width, "to": low + (i + 1) * width, "count": c} for i, c in enumerate(counts)]


def football_field(case, comps: dict, precedents: dict, sens: dict, bids: dict) -> list[dict]:
    m = case.market
    dcf_values = [v for row in sens["dcf_wacc_growth"]["values"] for v in row]
    inner = [row[1:4] for row in sens["dcf_wacc_growth"]["values"][1:4]]
    inner_values = [v for row in inner for v in row]
    bars = [
        {"method": "52-week trading range", "low": m["week52_low"], "high": m["week52_high"]},
        {"method": f"Trading comps EV/EBITDA, {comps['basis']} (Q1-Q3)",
         "low": comps["implied_price"]["ev_ebitda"]["q1"], "high": comps["implied_price"]["ev_ebitda"]["q3"]},
        {"method": f"Trading comps P/E, {comps['basis']} (Q1-Q3)",
         "low": comps["implied_price"]["pe"]["q1"], "high": comps["implied_price"]["pe"]["q3"]},
        {"method": f"Precedents EV/EBITDA, {precedents['basis']} (Q1-Q3)",
         "low": precedents["implied_price"]["ev_ebitda"]["q1"], "high": precedents["implied_price"]["ev_ebitda"]["q3"]},
        {"method": "Precedent premiums to unaffected (Q1-Q3)",
         "low": precedents["implied_price"]["premium"]["q1"], "high": precedents["implied_price"]["premium"]["q3"]},
        {"method": "DCF, WACC +/-0.5%, g +/-0.5%", "low": min(inner_values), "high": max(inner_values),
         "outer_low": min(dcf_values), "outer_high": max(dcf_values)},
    ]
    if bids["price_at_hurdle_irr"] is not None and bids["price_at_hurdle_plus_5"] is not None:
        hurdle = case.transaction["hurdle_irr"]
        bars.append({"method": f"LBO ability to pay ({hurdle + 0.05:.0%}-{hurdle:.0%} sponsor IRR)",
                     "low": bids["price_at_hurdle_plus_5"], "high": bids["price_at_hurdle_irr"]})
    return bars


def analyze(case) -> dict:
    """Everything the workbook and memo need, computed once."""
    base = run_lbo(case)
    capital = wacc(case)
    valuation = dcf(case, discount_rate=capital["wacc"])
    comps, precedents = trading_comps(case), precedent_transactions(case)
    sens = sensitivities(case)
    bids = breakevens(case)
    return {
        "case": {"name": case.name, "company": case.company, "illustrative": case.illustrative,
                 "currency": case.raw.get("currency", ""), "historical_years": list(case.historical_years),
                 "projection_years": list(case.projection_years)},
        "lbo": base, "scenarios": scenario_table(case), "wacc": capital, "dcf": valuation,
        "comps": comps, "precedents": precedents, "sensitivities": sens, "breakevens": bids,
        "monte_carlo": monte_carlo(case),
        "football_field": football_field(case, comps, precedents, sens, bids),
    }
