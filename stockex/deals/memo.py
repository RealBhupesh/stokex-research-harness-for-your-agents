"""Investment committee memo, generated from the analysis results.

The memo is a list of blocks rendered to Markdown and to self-contained HTML
with inline SVG charts. Every number comes from the results, and the
recommendation follows stated rules rather than taste. Regulatory points are
stated as considerations to confirm with counsel, not as advice.
"""

from html import escape

from .lbo import run_lbo

DECISIONS = ("APPROVE", "APPROVE WITH CONDITIONS", "RETURN FOR WORK", "DECLINE")


def money(value: float, unit: str = "cr") -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}₹{abs(value):,.0f} {unit}".strip()


def price(value: float | None) -> str:
    return "n/a" if value is None else f"₹{value:,.2f}"


def pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def points(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f} percentage points"


def mult(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}x"


def recommendation(case, results) -> dict:
    """Rule-based decision: returns, capital preservation, covenants and price discipline."""
    tx = case.transaction
    scenarios = results["scenarios"]["rows"]
    base, bids, mc = scenarios["base"], results["breakevens"], results["monte_carlo"]
    downside = scenarios.get("downside", base)
    offer, max_bid = bids["offer_price"], bids["max_bid"]
    dcf_value = results["dcf"]["gordon"]["value_per_share"]
    conditions, failures = [], []
    if base["irr"] < tx["hurdle_irr"]:
        failures.append(f"Base-case IRR of {pct(base['irr'])} is below the {pct(tx['hurdle_irr'], 0)} hurdle.")
    if base["moic"] < tx["target_moic"]:
        failures.append(f"Base-case MOIC of {mult(base['moic'], 2)} is below the {mult(tx['target_moic'], 2)} target.")
    if base["first_breach"]:
        failures.append(f"The base case breaches {', '.join(base['first_breach']['tests'])} in "
                        f"{base['first_breach']['year']}.")
    if max_bid is None or offer > max_bid + 1e-9:
        failures.append(f"The offer of {price(offer)} exceeds the maximum bid of {price(max_bid)}.")
    if downside["first_breach"]:
        conditions.append(f"Reset or re-sculpt covenants: the downside case breaches "
                          f"{', '.join(downside['first_breach']['tests'])} in {downside['first_breach']['year']}.")
    if max_bid is not None and offer <= max_bid and max_bid / offer - 1 < 0.05:
        conditions.append(f"Hold a walk-away price of {price(max_bid)}: headroom to the maximum bid is only "
                          f"{pct(max_bid / offer - 1)}.")
    if mc.get("paths") and mc["probability_hurdle"] < 0.5:
        conditions.append(f"Only {pct(mc['probability_hurdle'], 0)} of simulated outcomes clear the hurdle; "
                          "underwrite the value-creation plan before signing.")
    if dcf_value < offer:
        conditions.append(f"The standalone DCF ({price(dcf_value)}) is below the offer: returns rely on the "
                          "sponsor plan and the exit multiple, not on buying below intrinsic value.")
    if downside["moic"] < 0.75 or base["irr"] < tx["hurdle_irr"] - 0.05:
        decision = "DECLINE"
    elif failures:
        decision = "RETURN FOR WORK"
    elif conditions:
        decision = "APPROVE WITH CONDITIONS"
    else:
        decision = "APPROVE"
    return {"decision": decision, "failures": failures, "conditions": conditions}


def _blocks(case, results) -> list:
    tx, c = case.transaction, case
    lbo = results["lbo"]
    su, r, cov, plan = lbo["sources_uses"], lbo["returns"], lbo["covenants"], lbo["plan"]
    fin = lbo["statements"]
    scen, bids, mc = results["scenarios"], results["breakevens"], results["monte_carlo"]
    d, w = results["dcf"], results["wacc"]
    comps, prec = results["comps"], results["precedents"]
    rec = recommendation(case, results)
    years = list(case.projection_years)
    hold = r["holding_years"]
    rev0 = case.historicals["revenue"][-1]
    margin0 = case.ltm_ebitda / rev0
    downside = scen["rows"].get("downside")
    base_row = scen["rows"]["base"]
    b = r["bridge"]
    gain = b["total_equity_gain"]
    blocks = []
    add = blocks.append

    add(("title", f"{case.name}: Investment Committee Memorandum"))
    add(("subtitle", f"{case.company} | {case.raw.get('sector', '')} | Proposed take-private by a financial sponsor"))
    if case.illustrative:
        add(("banner", "Illustrative case. The company and every figure are fictional and exist to show the method. "
                       "Nothing here is investment, legal or tax advice."))
    add(("decision", rec["decision"],
         f"Bid {price(su['offer_price'])} per share ({pct(su['premium'], 0)} premium to the unaffected "
         f"{price(case.market['unaffected_price'])}), with a walk-away price of {price(bids['max_bid'])}."))

    add(("h2", "1. Executive summary"))
    add(("ul", [
        f"Entry at {money(su['entry_ev'])} enterprise value, {mult(su['entry_multiple'])} LTM EBITDA of "
        f"{money(su['ltm_ebitda'])}; equity purchase {money(su['equity_purchase'])}.",
        f"Financing: {money(su['new_debt'])} of debt ({mult(su['leverage'], 2)} LTM EBITDA) and "
        f"{money(su['sponsor_equity'])} of sponsor equity, plus {money(su['rollover_equity'])} promoter rollover; "
        f"equity is {pct(su['equity_contribution'], 0)} of the capitalisation.",
        f"Base case: {pct(r['irr'])} IRR and {mult(r['moic'], 2)} MOIC over {hold} years, exiting in {r['exit_year']} "
        f"at {mult(r['exit_multiple'])} EBITDA of {money(r['exit_ebitda'])}.",
        (f"Probability-weighted across cases: {pct(scen['probability_weighted']['irr'])} IRR and "
         f"{mult(scen['probability_weighted']['moic'], 2)} MOIC." if scen["probability_weighted"] else
         "Only a base case was supplied."),
        (f"Monte Carlo ({mc['paths']:,} paths): median IRR {pct(mc['irr']['p50'])}, 5th-95th percentile "
         f"{pct(mc['irr']['p5'])} to {pct(mc['irr']['p95'])}; {pct(mc['probability_hurdle'], 0)} clear the hurdle, "
         f"{pct(mc['probability_loss'], 1)} lose money and {pct(mc['probability_covenant_breach'], 0)} breach a covenant."
         if mc.get("paths") else "Monte Carlo was not run."),
        (f"Downside case: {mult(downside['moic'], 2)} MOIC ({pct(downside['irr'])} IRR); capital is "
         f"{'preserved' if downside['moic'] >= 1 else 'impaired'}." if downside else "No downside case supplied."),
        f"Maximum bid {price(bids['max_bid'])}, set by {bids['max_bid_binding_constraint']}.",
    ]))
    if rec["failures"]:
        add(("h3", "Why this cannot be approved as structured"))
        add(("ul", rec["failures"]))
    if rec["conditions"]:
        add(("h3", "Conditions"))
        add(("ul", rec["conditions"]))

    add(("h2", "2. Investment thesis and what has to be true"))
    if case.raw.get("thesis"):
        add(("ul", list(case.raw["thesis"])))
    add(("p", "The base case needs four things to happen:"))
    add(("ul", [
        f"Revenue compounds at {pct(base_row['revenue_cagr'])} a year from {money(rev0)} to "
        f"{money(plan['revenue'][hold - 1])}.",
        f"The EBITDA margin expands from {pct(margin0)} to {pct(base_row['exit_ebitda_margin'])}.",
        f"Free cash flow pays down {money(b['deleveraging'])} of net debt.",
        f"A buyer pays {mult(r['exit_multiple'])} EBITDA in {r['exit_year']}, against {mult(su['entry_multiple'])} at "
        "entry.",
    ]))

    add(("h2", "3. Transaction overview"))
    add(("h3", "Sources and uses"))
    rows = [[k.replace("_", " ").capitalize(), money(v), pct(v / su["total_uses"])] for k, v in su["uses"].items()]
    add(("table", ["Uses", f"{case.raw.get('currency', '')}", "% of total"],
         rows + [["Total uses", money(su["total_uses"]), "100.0%"]]))
    rows = [[k if k[0].isupper() else k.replace("_", " ").capitalize(), money(v), pct(v / su["total_sources"])]
            for k, v in su["sources"].items()]
    add(("table", ["Sources", f"{case.raw.get('currency', '')}", "% of total"],
         rows + [["Total sources", money(su["total_sources"]), "100.0%"]]))
    add(("h3", "Capital structure at close"))
    rows = []
    for t, sized in zip(case.tranches, su["tranches"]):
        coupon = pct(t.cash_rate, 2) + (f" cash + {pct(t.pik_rate, 2)} PIK" if t.pik_rate else " cash")
        rows.append([t.name, money(sized["principal"]), mult(sized["principal"] / su["ltm_ebitda"], 2), coupon,
                     "Amortising, swept" if t.sweep else ("Amortising" if t.kind == "amortizing" else "Bullet")])
    rows.append(["Revolver (undrawn at close)", money(case.revolver["commitment"]) + " commitment", "-",
                 pct(case.revolver["cash_rate"], 2), "Liquidity backstop"])
    rows.append(["Total debt", money(su["new_debt"]), mult(su["leverage"], 2), "", ""])
    add(("table", ["Tranche", "Amount", "x LTM EBITDA", "Pricing", "Terms"], rows))

    add(("h2", "4. Projections (base case)"))
    header = ["", f"{case.historical_years[-1]}A"] + [f"{y}E" for y in years]
    add(("table", header, [
        ["Revenue", money(rev0, "")] + [money(x, "") for x in plan["revenue"]],
        ["Growth", pct(rev0 / case.historicals["revenue"][-2] - 1) if len(case.historicals["revenue"]) > 1 else ""]
        + [pct(x) for x in plan["revenue_growth"]],
        ["EBITDA", money(case.ltm_ebitda, "")] + [money(x, "") for x in plan["ebitda"]],
        ["EBITDA margin", pct(margin0)] + [pct(x) for x in plan["ebitda_margin"]],
        ["Net income", money(case.historicals["revenue"][-1] - case.historicals["cogs"][-1] - case.historicals["opex"][-1]
                             - case.historicals["da"][-1] - case.historicals["finance_cost"][-1]
                             + case.historicals["other_income"][-1] - case.historicals["tax"][-1], "")]
        + [money(x, "") for x in fin["net_income"]],
        ["Unlevered FCF", ""] + [money(x, "") for x in plan["fcff"]],
        ["Net debt", money(su["net_debt_at_close"], "") + " (close)"] + [money(x, "") for x in fin["net_debt"]],
        ["Net debt / EBITDA", mult(su["net_debt_at_close"] / su["ltm_ebitda"], 2)]
        + [mult(x, 2) for x in cov["net_leverage"]],
    ]))
    add(("note", f"{case.raw.get('currency', '')}. Interest accrues on opening balances. Tax at "
                 f"{pct(case.projection['tax_rate'], 2)}; interest above {pct(case.tax['interest_cap_pct_ebitda'], 0)} of "
                 f"tax EBITDA on caught debt is disallowed and carried forward "
                 f"({money(sum(fin['disallowed_interest']))} over the plan)."))

    add(("h2", "5. Returns"))
    rows = [[name.title(), pct(row["probability"], 0), pct(row["revenue_cagr"]), pct(row["exit_ebitda_margin"]),
             mult(row["exit_multiple"]), pct(row["irr"]), mult(row["moic"], 2),
             row["first_breach"]["year"] + " " + "/".join(row["first_breach"]["tests"]) if row["first_breach"] else "None"]
            for name, row in scen["rows"].items()]
    if scen["probability_weighted"]:
        rows.append(["Probability-weighted", "100%", "", "", "", pct(scen["probability_weighted"]["irr"]),
                     mult(scen["probability_weighted"]["moic"], 2), ""])
    add(("table", ["Case", "Weight", "Revenue CAGR", "Exit margin", "Exit multiple", "IRR", "MOIC", "First breach"], rows))
    add(("h3", "Returns by exit year (base case, live exit multiple)"))
    add(("table", ["Exit year"] + [x["exit_year"] for x in lbo["returns_by_exit_year"]],
         [["IRR"] + [pct(x["irr"]) for x in lbo["returns_by_exit_year"]],
          ["MOIC"] + [mult(x["moic"], 2) for x in lbo["returns_by_exit_year"]]]))
    add(("h3", "Where the equity value comes from"))
    add(("chart", "bridge", b))
    add(("table", ["Driver", "Value", "Share of equity gain"], [
        ["EBITDA growth (at the entry multiple)", money(b["ebitda_growth"]), pct(b["ebitda_growth"] / gain)],
        ["Multiple expansion / (contraction)", money(b["multiple_change"]), pct(b["multiple_change"] / gain)],
        ["Net debt paydown", money(b["deleveraging"]), pct(b["deleveraging"] / gain)],
        ["Fees and exit costs", money(b["fees_and_costs"]), pct(b["fees_and_costs"] / gain)],
        ["Total equity value created", money(gain), "100.0%"],
    ]))
    add(("p", f"Value creation is operational: EBITDA growth explains {pct(b['ebitda_growth'] / gain, 0)} of the gain. "
              f"The plan assumes {'multiple contraction' if b['multiple_change'] < 0 else 'multiple expansion'} of "
              f"{mult(abs(r['exit_multiple'] - su['entry_multiple']))}, so the return does not depend on a richer exit "
              "market." if b["multiple_change"] < 0 else
              f"Multiple expansion contributes {pct(b['multiple_change'] / gain, 0)} of the gain; treat that share as "
              "market-dependent."))
    if mc.get("paths"):
        add(("h3", "Distribution of outcomes"))
        add(("chart", "histogram", mc))
        add(("note", f"{mc['paths']:,} seeded paths. Revenue growth shift ~ N(0, {pct(mc['assumptions']['revenue_growth_sd'])}), "
                     f"margin shift ~ N(0, {pct(mc['assumptions']['ebitda_margin_sd'])}) and exit multiple ~ triangular("
                     f"{mult(mc['assumptions']['exit_multiple_low'])}, {mult(mc['assumptions']['exit_multiple_mode'])}, "
                     f"{mult(mc['assumptions']['exit_multiple_high'])}). Shifts apply to every year of a path."))

    add(("h2", "6. Valuation cross-check"))
    add(("chart", "football", {"bars": results["football_field"], "offer": su["offer_price"],
                               "unaffected": case.market["unaffected_price"], "max_bid": bids["max_bid"]}))
    add(("table", ["Method", "Low", "High"], [[bar["method"], price(bar["low"]), price(bar["high"])]
                                               for bar in results["football_field"]]))
    gordon, exit_ = d["gordon"], d["exit"]
    add(("ul", [
        f"WACC {pct(w['wacc'], 2)}: cost of equity {pct(w['cost_of_equity'], 2)} (risk-free {pct(c.valuation['risk_free'], 2)}, "
        f"relevered beta {w['relevered_beta']:.2f} from a median unlevered peer beta of {w['unlevered_beta']:.2f}, ERP "
        f"{pct(c.valuation['equity_risk_premium'], 2)}, size premium {pct(c.valuation['size_premium'], 2)}) and after-tax "
        f"cost of debt {pct(w['after_tax_cost_of_debt'], 2)} at {pct(w['weight_debt'], 0)} debt.",
        f"DCF (Gordon growth at {pct(d['terminal_growth'], 1)}): {price(gordon['value_per_share'])} per share, "
        f"{pct(gordon['terminal_share'], 0)} of EV from the terminal value. That implies an exit multiple of "
        f"{mult(d['implied_exit_multiple'])}.",
        f"DCF (exit at {mult(d['exit_multiple'])}): {price(exit_['value_per_share'])} per share. That implies "
        f"{pct(d['implied_terminal_growth'], 1)} perpetual growth, well above a sustainable nominal rate. The gap is "
        "the usual India mid-cap tension: market multiples price in a longer high-growth runway than a five-year "
        "explicit forecast captures.",
        f"Trading comps ({comps['basis']}): peers trade at a median {mult(comps['stats']['ev_ebitda']['median'])} EV/EBITDA "
        f"and {mult(comps['stats']['pe']['median'])} P/E. The target trades at "
        f"{mult(comps['target_multiples']['ev_ebitda'])} and {mult(comps['target_multiples']['pe'])} at the unaffected price.",
        f"Precedents: median {mult(prec['stats']['ev_ebitda']['median'])} LTM EBITDA and a "
        f"{pct(prec['stats']['premium']['median'], 0)} premium. The highest precedent is "
        f"{mult(prec['stats']['ev_ebitda']['max'])}, above our ability to pay; expect competition from strategic buyers.",
    ]))

    add(("h2", "7. Downside: what breaks the deal"))
    add(("table", ["Test", "Threshold"], [
        ["Exit multiple for 1.0x (capital back)", mult(bids["exit_multiple_for_1x"])],
        ["Exit multiple for 2.0x", mult(bids["exit_multiple_for_2x"])],
        [f"Exit multiple for the {pct(tx['hurdle_irr'], 0)} hurdle", mult(bids["exit_multiple_for_hurdle_irr"])],
        ["EBITDA shortfall (every year) before the first covenant breach",
         pct(bids["ebitda_haircut_to_covenant_breach"])],
        ["EBITDA shortfall before cash runs out (revolver exhausted)", pct(bids["ebitda_haircut_to_liquidity_shortfall"])],
        ["EBITDA shortfall before the sponsor loses money (at the base exit multiple)",
         pct(bids["ebitda_haircut_to_1x"])],
        [f"Offer price at which the base case earns {pct(tx['hurdle_irr'], 0)}", price(bids["price_at_hurdle_irr"])],
        ["Offer price at which the downside case returns 1.0x", price(bids["price_at_downside_1x"])],
    ]))
    add(("h3", "Covenant headroom (base case)"))
    add(("table", ["", *[f"{y}E" for y in years]], [
        ["Net debt / EBITDA", *[mult(x, 2) for x in cov["net_leverage"]]],
        ["Maximum", *[mult(x, 2) for x in case.covenants["max_net_leverage"]]],
        ["Interest cover", *[mult(x, 2) for x in cov["interest_cover"]]],
        ["DSCR", *[mult(x, 2) for x in cov["dscr"]]],
        ["EBITDA cushion", *[pct(x) for x in cov["ebitda_cushion"]]],
    ]))
    if downside and downside["first_breach"]:
        dl = run_lbo(case, "downside")
        add(("p", f"The downside case breaches {', '.join(downside['first_breach']['tests'])} in "
                  f"{downside['first_breach']['year']}, when DSCR falls to {mult(dl['covenants']['dscr'][downside['first_breach']['index']], 2)} "
                  f"against a {mult(case.covenants['min_dscr'], 2)} minimum. Lenders would hold a cure or reset "
                  "right. Negotiate equity-cure rights and a DSCR set below the downside path, or reduce scheduled "
                  "amortisation in the first two years."))

    add(("h2", "8. India structuring considerations"))
    add(("p", "These are the points deal counsel and tax advisers need to confirm for this structure. Rules change; "
              "check the current position before relying on any of them."))
    add(("ul", [
        "Takeover Code: buying the promoter stake pushes the acquirer past 25%, which triggers a mandatory open offer "
        "for at least 26% more under the SEBI SAST Regulations. The offer price has to clear the regulation's floor "
        "(including the volume-weighted average market price tests), so the floor may sit above our model price.",
        "Delisting: taking the company private needs 90% ownership after the offer under the SEBI Delisting Regulations, "
        "with price discovery by reverse book building (or the newer fixed-price route where it is available). Model "
        "the outcome where delisting fails: the sponsor stays a listed majority owner and the remaining public "
        "shareholders keep their claim on dividends.",
        "Acquisition debt: Indian banks have historically been restricted from funding share acquisitions, and ECB "
        "end-use rules bar foreign currency borrowing for buying shares. That is why the acquisition debt here is HoldCo "
        "NCDs placed with private credit funds (FPIs or AIFs). RBI has been loosening acquisition-finance rules, so check "
        "whether bank debt is now cheaper.",
        "Structural subordination: HoldCo NCD holders rank behind OpCo creditors and are paid from dividends the OpCo "
        "upstreams. Section 67 of the Companies Act restricts a public company from giving financial assistance to buy "
        "its own shares, so OpCo security and debt push-down normally wait until the company is delisted and converted "
        "to private, or merged with the HoldCo.",
        f"Interest deductibility: the model applies a {pct(case.tax['interest_cap_pct_ebitda'], 0)}-of-EBITDA cap "
        f"(s.94B) to the HoldCo NCDs. That disallows {money(sum(fin['disallowed_interest']))} of interest over the "
        "plan; the disallowed amount is carried forward and deducted later as headroom allows. The cap applies only to "
        "debt from, or guaranteed by, non-resident associated enterprises. If the NCDs are placed without a sponsor "
        "guarantee it may not apply. Check withholding tax on interest paid to FPIs as well.",
        f"Tax rate: {pct(case.projection['tax_rate'], 2)} under the concessional regime (s.115BAA), with no MAT. The "
        "Income-tax Act, 2025 replaces the 1961 Act from April 2026 and renumbers these provisions; confirm the "
        "equivalent sections.",
    ]))

    add(("h2", "9. Key risks and mitigants"))
    add(("table", ["Risk", "Evidence from the model", "Mitigant / diligence"], [
        ["Margin expansion does not happen",
         f"Plan takes EBITDA margin from {pct(margin0)} to {pct(base_row['exit_ebitda_margin'])}; "
         f"{pct(bids['ebitda_haircut_to_covenant_breach'])} lower EBITDA trips a covenant.",
         "Procurement and pricing diligence on the commodity spice basket; management incentive tied to EBITDA."],
        ["Exit multiple compresses",
         f"Each 1.0x of exit multiple moves IRR by about {points(_irr_per_turn(results))}; 1.0x is returned at "
         f"{mult(bids['exit_multiple_for_1x'])}.",
         "Exit planning for a strategic sale or IPO; a credible dual-track route."],
        ["Leverage too heavy in the early years",
         f"Net leverage {mult(su['net_debt_at_close'] / su['ltm_ebitda'], 2)} at close and "
         f"{mult(cov['net_leverage'][0], 2)} after year one; minimum EBITDA cushion "
         f"{pct(cov['minimum_ebitda_cushion'])} in the base case.",
         "Covenant set with at least 25% headroom; equity cure rights; revolver sized for working-capital peaks."],
        ["Working capital absorbs cash",
         "The downside case adds inventory days; cash sweep stops while the revolver is drawn.",
         "Inventory and channel-stock diligence; seasonal working-capital facility."],
        ["Regulatory path (open offer, delisting)",
         "Returns assume 100% ownership and full cash access.",
         "Model the outcome where delisting fails; secure promoter support and irrevocable undertakings."],
    ]))

    add(("h2", "10. What would make us wrong"))
    gap = _growth_for_hurdle_gap(case)
    add(("ul", [
        (f"If revenue grows {points(abs(gap))} a year {'slower' if gap < 0 else 'faster'} than plan, the base case lands "
         f"exactly at the {pct(tx['hurdle_irr'], 0)} hurdle." if gap is not None
         else "Growth sensitivity could not be bracketed."),
        f"If buyers in {r['exit_year']} pay less than {mult(bids['exit_multiple_for_hurdle_irr'])}, we miss the hurdle.",
        (f"If the standalone DCF ({price(d['gordon']['value_per_share'])}) is right about intrinsic value, the offer pays "
         f"{price(su['offer_price'] - d['gordon']['value_per_share'])} a share above it. That premium is paid for the "
         "sponsor plan, so the plan has to be delivered." if su["offer_price"] > d["gordon"]["value_per_share"] else
         f"The offer is below the standalone DCF ({price(d['gordon']['value_per_share'])}), so part of the return is "
         "bought, not built; check why the market disagrees."),
        "If a strategic bidder emerges at precedent multiples, we should not chase: our ability to pay stops at "
        f"{price(bids['max_bid'])}.",
    ]))

    add(("h2", "11. Diligence priorities and first 100 days"))
    add(("ol", [
        "Commercial diligence on the adjacent-state expansion: distributor economics, shelf share and the pace of the "
        "revenue plan.",
        "Gross margin bridge: commodity hedging, pass-through lag and premium-mix assumptions.",
        "Quality of earnings: normalise promoter-related transactions and one-offs; reconcile cash conversion.",
        "Working capital: inventory ageing, channel stock and receivable quality by channel.",
        "Tax and structure: s.94B exposure, withholding on NCD interest, stamp duty and the post-delisting merger plan.",
        "100-day plan: CFO and procurement hires, monthly KPI pack (fill rate, distribution reach, gross margin by SKU) "
        "and a lender reporting calendar.",
    ]))

    add(("h2", "Appendix: model integrity and method"))
    checks = lbo["checks"]
    add(("ul", [
        ("Integrity checks: all pass. Sources equal uses, the balance sheet balances and cash ties in every year, and "
         "the value-creation bridge reconciles, each to within 0.000001." if checks["ok"] else
         f"Integrity checks FAILED: {checks}."),
        "The Excel model uses live formulas throughout. The STOCKEX tests recompute every formula from the inputs and "
        "require it to match this engine, and LibreOffice recalculation is checked the same way when it is installed.",
        "Conventions: fiscal years end in March; the deal closes on the last balance sheet date; interest accrues on "
        "opening balances; goodwill is the price over book equity, with no purchase-price allocation write-ups; "
        "deferred tax is ignored.",
        "Monte Carlo paths are seeded and reproducible. Sensitivities and breakevens re-run the full integrated model.",
    ]))
    return blocks


def _irr_per_turn(results) -> float:
    grid = results["sensitivities"]["irr_entry_exit"]
    mid = len(grid["rows"]) // 2
    points = [(x, v) for x, v in zip(grid["cols"], grid["values"][mid]) if v is not None]
    if len(points) < 2:
        return None
    return (points[-1][1] - points[0][1]) / (points[-1][0] - points[0][0])


def _growth_for_hurdle_gap(case) -> float | None:
    from .analysis import solve
    return solve(lambda g: run_lbo(case, growth_shift=g)["returns"]["irr"], case.transaction["hurdle_irr"], -0.2, 0.2)


# ---------- rendering ----------

def to_markdown(case, results) -> str:
    out = []
    for block in _blocks(case, results):
        kind = block[0]
        if kind == "title":
            out.append(f"# {block[1]}\n")
        elif kind == "subtitle":
            out.append(f"_{block[1]}_\n")
        elif kind == "banner":
            out.append(f"> **{block[1]}**\n")
        elif kind == "decision":
            out.append(f"**Recommendation: {block[1]}.** {block[2]}\n")
        elif kind == "h2":
            out.append(f"## {block[1]}\n")
        elif kind == "h3":
            out.append(f"### {block[1]}\n")
        elif kind == "p":
            out.append(block[1] + "\n")
        elif kind == "note":
            out.append(f"_{block[1]}_\n")
        elif kind == "ul":
            out.append("\n".join(f"- {item}" for item in block[1]) + "\n")
        elif kind == "ol":
            out.append("\n".join(f"{i}. {item}" for i, item in enumerate(block[1], 1)) + "\n")
        elif kind == "table":
            header, rows = block[1], block[2]
            lines = ["| " + " | ".join(header) + " |", "|" + "|".join(" --- " for _ in header) + "|"]
            lines += ["| " + " | ".join(str(x) for x in row) + " |" for row in rows]
            out.append("\n".join(lines) + "\n")
        elif kind == "chart":
            continue
    return "\n".join(out)


_CSS = """
:root{--ink:#1b1f2a;--muted:#5b6475;--rule:#d9dee7;--navy:#1f3864;--accent:#2f6db5;--good:#1d7a46;--bad:#b3261e;
--band:#f3f5f9;--bg:#ffffff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "Georgia",
"Times New Roman",serif}main{max-width:960px;margin:0 auto;padding:40px 24px 80px}
h1{font:700 30px/1.2 "Helvetica Neue",Arial,sans-serif;color:var(--navy);margin:0 0 6px}
h2{font:700 19px/1.3 "Helvetica Neue",Arial,sans-serif;color:var(--navy);margin:36px 0 10px;padding-top:14px;
border-top:2px solid var(--navy)}h3{font:700 15px/1.3 "Helvetica Neue",Arial,sans-serif;margin:22px 0 8px}
.subtitle{color:var(--muted);font-style:italic;margin-bottom:18px}.banner{background:#fff4e5;border-left:4px solid
#c55a11;padding:10px 14px;margin:14px 0;font:600 13px/1.5 "Helvetica Neue",Arial,sans-serif}
.decision{display:flex;gap:16px;align-items:center;background:var(--band);border:1px solid var(--rule);padding:16px 18px;
margin:18px 0}.decision b{font:800 15px/1.2 "Helvetica Neue",Arial,sans-serif;letter-spacing:.04em;color:#fff;
background:var(--navy);padding:8px 12px;white-space:nowrap}.decision.cond b{background:#8a5a00}.decision.no b{background:var(--bad)}
.decision.ok b{background:var(--good)}table{border-collapse:collapse;width:100%;margin:8px 0 14px;font:13px/1.4
"Helvetica Neue",Arial,sans-serif;font-variant-numeric:tabular-nums}th{background:var(--navy);color:#fff;text-align:right;
padding:6px 8px;font-weight:600}th:first-child,td:first-child{text-align:left}td{padding:5px 8px;border-bottom:1px solid
var(--rule);text-align:right}tr.total td{font-weight:700;border-top:1px solid var(--ink)}.note{color:var(--muted);
font-size:13px;font-style:italic}.table-wrap{overflow-x:auto}svg{display:block;width:100%;height:auto;margin:8px 0 4px}
svg text{font:12px "Helvetica Neue",Arial,sans-serif;fill:var(--ink)}li{margin:4px 0}
@media print{main{padding:0}h2{break-after:avoid}table,svg{break-inside:avoid}}
@media (max-width:640px){body{font-size:14px}main{padding:24px 16px 60px}.decision{flex-direction:column;align-items:flex-start}}
"""


def _svg_football(data) -> str:
    bars = data["bars"]
    values = [v for bar in bars for v in (bar["low"], bar["high"], bar.get("outer_low", bar["low"]),
                                           bar.get("outer_high", bar["high"]))]
    values += [data["offer"], data["unaffected"]] + ([data["max_bid"]] if data["max_bid"] else [])
    lo, hi = min(values) * 0.92, max(values) * 1.05
    width, left, right, row_h, top = 900, 370, 40, 30, 20
    height = top + row_h * len(bars) + 72
    x = lambda v: left + (v - lo) / (hi - lo) * (width - left - right)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Valuation football field">']
    for i, bar in enumerate(bars):
        y = top + i * row_h
        parts.append(f'<text x="{left - 10}" y="{y + 18}" text-anchor="end">{escape(bar["method"])}</text>')
        if "outer_low" in bar:
            parts.append(f'<rect x="{x(bar["outer_low"]):.1f}" y="{y + 6}" width="{x(bar["outer_high"]) - x(bar["outer_low"]):.1f}" '
                         f'height="16" fill="#c9d6ea"/>')
        parts.append(f'<rect x="{x(bar["low"]):.1f}" y="{y + 6}" width="{max(2, x(bar["high"]) - x(bar["low"])):.1f}" '
                     f'height="16" fill="#2f6db5"/>')
        low_x, high_x = x(bar.get("outer_low", bar["low"])), x(bar.get("outer_high", bar["high"]))
        parts.append(f'<text x="{low_x - 4:.1f}" y="{y + 18}" text-anchor="end" font-size="11">{bar["low"]:,.0f}</text>')
        parts.append(f'<text x="{high_x + 4:.1f}" y="{y + 18}" font-size="11">{bar["high"]:,.0f}</text>')
    bottom = top + row_h * len(bars)
    for k, (label, value, color, dash, anchor) in enumerate((
            ("Unaffected", data["unaffected"], "#5b6475", "4 3", "middle"),
            ("Offer", data["offer"], "#1b1f2a", "", "end"), ("Max bid", data["max_bid"], "#b3261e", "6 3", "start"))):
        if value is None:
            continue
        parts.append(f'<line x1="{x(value):.1f}" x2="{x(value):.1f}" y1="{top - 6}" y2="{bottom + 4 + 16 * k}" '
                     f'stroke="{color}" stroke-width="1.6" stroke-dasharray="{dash}"/>')
        nudge = {"end": -4, "start": 4, "middle": 0}[anchor]
        parts.append(f'<text x="{x(value) + nudge:.1f}" y="{bottom + 18 + 16 * k}" text-anchor="{anchor}" fill="{color}" '
                     f'font-weight="700">{label} {value:,.0f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_bridge(b) -> str:
    steps = [("EBITDA growth", b["ebitda_growth"]), ("Multiple", b["multiple_change"]),
             ("Debt paydown", b["deleveraging"]), ("Fees and costs", b["fees_and_costs"])]
    running, items = 0.0, []
    for label, value in steps:
        items.append((label, running, running + value, value))
        running += value
    items.append(("Equity value created", 0.0, running, running))
    lo = min(0.0, *(min(a, b_) for _, a, b_, _ in items))
    hi = max(*(max(a, b_) for _, a, b_, _ in items))
    width, height, top, base_h = 900, 280, 20, 220
    col = (width - 40) / len(items)
    y = lambda v: top + (hi - v) / (hi - lo) * (base_h - top)  # noqa: E731
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Value creation bridge">',
             f'<line x1="20" x2="{width - 20}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#1b1f2a"/>']
    for i, (label, start, end, value) in enumerate(items):
        x0 = 20 + i * col + col * 0.18
        w = col * 0.64
        color = "#1f3864" if i == len(items) - 1 else ("#1d7a46" if value >= 0 else "#b3261e")
        parts.append(f'<rect x="{x0:.1f}" y="{min(y(start), y(end)):.1f}" width="{w:.1f}" '
                     f'height="{max(1.5, abs(y(start) - y(end))):.1f}" fill="{color}"/>')
        parts.append(f'<text x="{x0 + w / 2:.1f}" y="{min(y(start), y(end)) - 6:.1f}" text-anchor="middle" '
                     f'font-weight="700">{value:,.0f}</text>')
        parts.append(f'<text x="{x0 + w / 2:.1f}" y="{base_h + 34}" text-anchor="middle">{escape(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _svg_histogram(mc) -> str:
    buckets = mc["histogram"]
    peak = max(b["count"] for b in buckets) or 1
    width, height, top, base, left = 900, 230, 16, 180, 40
    col = (width - left - 20) / len(buckets)
    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Distribution of simulated IRRs">']
    for i, b in enumerate(buckets):
        h = b["count"] / peak * (base - top)
        color = "#2f6db5" if b["from"] >= 0 else "#b3261e"
        parts.append(f'<rect x="{left + i * col + 2:.1f}" y="{base - h:.1f}" width="{col - 4:.1f}" height="{h:.1f}" '
                     f'fill="{color}"/>')
        parts.append(f'<text x="{left + i * col + col / 2:.1f}" y="{base + 16}" text-anchor="middle" font-size="11">'
                     f'{b["from"] * 100:.0f}%</text>')
    parts.append(f'<line x1="{left}" x2="{width - 20}" y1="{base}" y2="{base}" stroke="#1b1f2a"/>')
    parts.append(f'<text x="{left}" y="{base + 40}">Sponsor IRR (bucket lower bound). Median {mc["irr"]["p50"] * 100:.1f}%, '
                 f'P(IRR &#8805; hurdle) {mc["probability_hurdle"] * 100:.0f}%.</text>')
    parts.append("</svg>")
    return "".join(parts)


def to_html(case, results) -> str:
    out = []
    decision_class = {"APPROVE": "ok", "APPROVE WITH CONDITIONS": "cond", "RETURN FOR WORK": "no", "DECLINE": "no"}
    for block in _blocks(case, results):
        kind = block[0]
        if kind == "title":
            out.append(f"<h1>{escape(block[1])}</h1>")
        elif kind == "subtitle":
            out.append(f'<div class="subtitle">{escape(block[1])}</div>')
        elif kind == "banner":
            out.append(f'<div class="banner">{escape(block[1])}</div>')
        elif kind == "decision":
            out.append(f'<div class="decision {decision_class[block[1]]}"><b>{escape(block[1])}</b>'
                       f"<span>{escape(block[2])}</span></div>")
        elif kind in {"h2", "h3"}:
            out.append(f"<{kind}>{escape(block[1])}</{kind}>")
        elif kind == "p":
            out.append(f"<p>{escape(block[1])}</p>")
        elif kind == "note":
            out.append(f'<p class="note">{escape(block[1])}</p>')
        elif kind in {"ul", "ol"}:
            out.append(f"<{kind}>" + "".join(f"<li>{escape(item)}</li>" for item in block[1]) + f"</{kind}>")
        elif kind == "table":
            head = "".join(f"<th>{escape(str(h))}</th>" for h in block[1])
            body = "".join(
                ('<tr class="total">' if str(row[0]).startswith(("Total", "Probability-weighted")) else "<tr>")
                + "".join(f"<td>{escape(str(x))}</td>" for x in row) + "</tr>" for row in block[2])
            out.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
        elif kind == "chart":
            out.append({"football": _svg_football, "bridge": _svg_bridge, "histogram": _svg_histogram}[block[1]](block[2]))
    title = escape(f"{case.name}: IC memo")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>{title}</title><style>{_CSS}</style></head>'
            f"<body><main>{''.join(out)}</main></body></html>\n")
