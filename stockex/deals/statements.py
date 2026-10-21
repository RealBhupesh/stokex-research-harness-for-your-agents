"""Integrated three-statement projection.

The build follows the order a deal team uses:
1. The operating plan (revenue to unlevered free cash flow) depends only on drivers.
2. The financed statements add the capital structure. Interest accrues on
   opening balances, so there is no circular reference. The revolver funds any
   shortfall below minimum cash. Excess cash pays down sweepable tranches in
   priority order.

Every period is checked: the balance sheet balances, and the change in cash
equals the cash flow statement.
"""

DAYS = 365.0


def operating_plan(case, drivers: dict, *, growth_shift: float = 0.0, margin_shift: float = 0.0,
                   ebitda_haircut: float = 0.0) -> dict:
    """Revenue to FCFF for each projection year.

    ``growth_shift`` is added to revenue growth every year. ``margin_shift`` is
    added to gross margin, so it moves the EBITDA margin one-for-one.
    ``ebitda_haircut`` cuts EBITDA proportionally by raising opex.
    """
    tax_rate = case.projection["tax_rate"]
    bs = case.balance_sheet
    rows = {key: [] for key in ("revenue", "gross_profit", "cogs", "opex", "ebitda", "da", "ebit", "capex",
                                "receivables", "inventory", "payables", "nwc", "delta_nwc", "nopat", "fcff",
                                "ebitda_margin", "revenue_growth")}
    revenue = case.historicals["revenue"][-1]
    nwc = bs["receivables"] + bs["inventory"] - bs["payables"]
    for i in range(case.years):
        growth = drivers["revenue_growth"][i] + growth_shift
        revenue = revenue * (1 + growth)
        gross_profit = revenue * (drivers["gross_margin"][i] + margin_shift)
        cogs = revenue - gross_profit
        base_opex = revenue * drivers["opex_pct"][i]
        opex = base_opex + ebitda_haircut * (gross_profit - base_opex)
        ebitda = gross_profit - opex
        da = revenue * drivers["da_pct"][i]
        ebit = ebitda - da
        capex = revenue * drivers["capex_pct"][i]
        receivables = revenue * drivers["receivable_days"][i] / DAYS
        inventory = cogs * drivers["inventory_days"][i] / DAYS
        payables = cogs * drivers["payable_days"][i] / DAYS
        new_nwc = receivables + inventory - payables
        delta_nwc = new_nwc - nwc
        nwc = new_nwc
        nopat = ebit * (1 - tax_rate)
        values = {
            "revenue": revenue, "gross_profit": gross_profit, "cogs": cogs, "opex": opex, "ebitda": ebitda,
            "da": da, "ebit": ebit, "capex": capex, "receivables": receivables, "inventory": inventory,
            "payables": payables, "nwc": new_nwc, "delta_nwc": delta_nwc, "nopat": nopat,
            "fcff": nopat + da - capex - delta_nwc, "ebitda_margin": ebitda / revenue, "revenue_growth": growth,
        }
        for key, value in values.items():
            rows[key].append(value)
    return rows


def financed_statements(case, plan: dict, opening: dict, tranches: list[dict]) -> dict:
    """Project the income statement, balance sheet, cash flow and debt schedule.

    ``opening`` is the pro forma balance sheet at close (see ``lbo.pro_forma_balance_sheet``).
    ``tranches`` holds the sized debt: name, principal, cash_rate, pik_rate,
    amortization, sweep and subject_to_interest_cap.
    """
    n = case.years
    tax_rate = case.projection["tax_rate"]
    cash_yield = case.projection["cash_yield"]
    minimum_cash = case.transaction["minimum_cash"]
    sweep_pct = case.transaction["sweep_pct"]
    revolver = case.revolver
    cap_pct = case.tax["interest_cap_pct_ebitda"]
    cap_threshold = case.tax["interest_cap_threshold"]
    fee_amortisation = opening["deferred_financing_fees"] / case.transaction["financing_fee_amortisation_years"]

    out = {key: [] for key in (
        "interest_income", "cash_interest", "pik_interest", "revolver_interest", "undrawn_fee",
        "fee_amortisation", "finance_cost", "pbt", "interest_for_cap", "interest_cap", "disallowed_interest",
        "carryforward_used", "carryforward", "taxable_income", "loss_used", "tax_losses", "tax", "net_income",
        "cfo", "cfi", "mandatory", "cash_available", "revolver_draw", "sweep_pool", "prepayment", "cff",
        "cash", "revolver", "total_debt", "net_debt", "receivables", "inventory", "payables",
        "other_current_assets", "ppe", "intangibles", "goodwill", "other_non_current_assets",
        "deferred_financing_fees", "other_current_liabilities", "other_non_current_liabilities", "equity",
        "total_assets", "total_claims", "balance_check", "cash_check", "liquidity_shortfall")}
    schedule = [{"name": t["name"], "opening": [], "cash_interest": [], "pik": [], "mandatory": [],
                 "prepayment": [], "closing": []} for t in tranches]

    cash, revolver_balance = opening["cash"], 0.0
    balances = [t["principal"] for t in tranches]
    ppe, dff, equity = opening["ppe"], opening["deferred_financing_fees"], opening["equity"]
    carryforward, tax_losses = 0.0, 0.0
    for i in range(n):
        ebitda, ebit = plan["ebitda"][i], plan["ebit"][i]
        cash_interest = [b * t["cash_rate"] for b, t in zip(balances, tranches)]
        pik = [b * t["pik_rate"] for b, t in zip(balances, tranches)]
        revolver_interest = revolver_balance * revolver["cash_rate"]
        undrawn_fee = (revolver["commitment"] - revolver_balance) * revolver["undrawn_fee"]
        interest_income = cash * cash_yield
        amortised_fee = min(dff, fee_amortisation)
        finance_cost = sum(cash_interest) + sum(pik) + revolver_interest + undrawn_fee + amortised_fee
        pbt = ebit - finance_cost + interest_income

        # Interest limitation (Income-tax Act, 1961 s.94B; carried into the 2025 Act): interest above
        # cap_pct of tax EBITDA is disallowed, up to the interest on caught debt, and carried forward.
        interest_for_cap = sum(cash_interest) + sum(pik) + revolver_interest + undrawn_fee
        tax_ebitda = ebitda + interest_income
        cap = cap_pct * tax_ebitda
        subject = sum(c + p for c, p, t in zip(cash_interest, pik, tranches) if t["subject_to_interest_cap"])
        disallowed = min(max(0.0, interest_for_cap - cap), subject) if subject > cap_threshold else 0.0
        carryforward_used = min(carryforward, max(0.0, cap - interest_for_cap))
        carryforward = carryforward + disallowed - carryforward_used
        taxable_before_losses = pbt + disallowed - carryforward_used
        loss_used = min(tax_losses, max(0.0, taxable_before_losses))
        tax_losses = tax_losses - loss_used + max(0.0, -taxable_before_losses)
        taxable = max(0.0, taxable_before_losses - loss_used)
        tax = taxable * tax_rate
        net_income = pbt - tax

        cfo = net_income + plan["da"][i] + sum(pik) + amortised_fee - plan["delta_nwc"][i]
        cfi = -plan["capex"][i]
        mandatory = [min(b + p, t["amortization"][i] * t["principal"]) for b, p, t in zip(balances, pik, tranches)]
        cash_available = cash + cfo + cfi - sum(mandatory) - minimum_cash
        draw = min(max(-cash_available, -revolver_balance), revolver["commitment"] - revolver_balance)
        after_revolver = cash_available + draw
        pool = max(0.0, after_revolver) * sweep_pct
        sweep_pool = pool
        prepayments = []
        for b, p, m, t in zip(balances, pik, mandatory, tranches):
            prepay = min(pool, b + p - m) if t["sweep"] else 0.0
            pool -= prepay
            prepayments.append(prepay)
        closing_cash = minimum_cash + after_revolver - sum(prepayments)
        cff = draw - sum(mandatory) - sum(prepayments)

        for k, t in enumerate(tranches):
            row = schedule[k]
            row["opening"].append(balances[k])
            row["cash_interest"].append(cash_interest[k])
            row["pik"].append(pik[k])
            row["mandatory"].append(mandatory[k])
            row["prepayment"].append(prepayments[k])
            balances[k] = balances[k] + pik[k] - mandatory[k] - prepayments[k]
            row["closing"].append(balances[k])

        cash_check = closing_cash - (cash + cfo + cfi + cff)
        cash = closing_cash
        revolver_balance += draw
        ppe = ppe + plan["capex"][i] - plan["da"][i]
        dff -= amortised_fee
        equity += net_income
        total_debt = sum(balances) + revolver_balance
        assets = (cash + plan["receivables"][i] + plan["inventory"][i] + opening["other_current_assets"] + ppe
                  + opening["intangibles"] + opening["goodwill"] + opening["other_non_current_assets"] + dff)
        claims = (plan["payables"][i] + opening["other_current_liabilities"] + revolver_balance + sum(balances)
                  + opening["other_non_current_liabilities"] + equity)
        values = {
            "interest_income": interest_income, "cash_interest": sum(cash_interest), "pik_interest": sum(pik),
            "revolver_interest": revolver_interest, "undrawn_fee": undrawn_fee, "fee_amortisation": amortised_fee,
            "finance_cost": finance_cost, "pbt": pbt, "interest_for_cap": interest_for_cap, "interest_cap": cap,
            "disallowed_interest": disallowed, "carryforward_used": carryforward_used, "carryforward": carryforward,
            "taxable_income": taxable, "loss_used": loss_used, "tax_losses": tax_losses, "tax": tax,
            "net_income": net_income, "cfo": cfo, "cfi": cfi, "mandatory": sum(mandatory),
            "cash_available": cash_available, "revolver_draw": draw, "sweep_pool": sweep_pool,
            "prepayment": sum(prepayments), "cff": cff, "cash": cash, "revolver": revolver_balance,
            "total_debt": total_debt, "net_debt": total_debt - cash, "receivables": plan["receivables"][i],
            "inventory": plan["inventory"][i], "payables": plan["payables"][i],
            "other_current_assets": opening["other_current_assets"], "ppe": ppe, "intangibles": opening["intangibles"],
            "goodwill": opening["goodwill"], "other_non_current_assets": opening["other_non_current_assets"],
            "deferred_financing_fees": dff, "other_current_liabilities": opening["other_current_liabilities"],
            "other_non_current_liabilities": opening["other_non_current_liabilities"], "equity": equity,
            "total_assets": assets, "total_claims": claims, "balance_check": assets - claims,
            "cash_check": cash_check, "liquidity_shortfall": after_revolver < -1e-9,
        }
        for key, value in values.items():
            out[key].append(value)
    out["tranches"] = schedule
    return out
