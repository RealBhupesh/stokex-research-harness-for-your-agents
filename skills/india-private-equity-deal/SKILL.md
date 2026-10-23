---
name: india-private-equity-deal
description: Underwrite a private equity buyout or take-private of an Indian company with an integrated three-statement LBO, DCF, comps, downside tests, a live-formula Excel model and an IC memo.
---
# India Private Equity Deal

Read ../../references/deal-modeling.md first. For the operating story and normalised financials, read ../../references/financial-normalization.md and ../../references/sector-kpis.md. For the IC review, read ../../references/investment-committee.md.

## Workflow

1. **Build the case.** Start from ../../examples/deals/project-saffron.json.
   - Historicals and the closing balance sheet come from reported, normalised figures, ideally from the evidence store at a dated cutoff (`--from-store`).
   - Write drivers for base, upside and downside cases. Each driver is a stated business claim (distribution reach, pricing, procurement), not a curve fit.
   - Size debt as multiples of LTM EBITDA. Choose instruments that are lawful for the structure; acquisition debt usually sits at HoldCo.
   - Comps and precedents need sources. Label anything illustrative.
2. **Run the model.** Run `python -m stockex.cli deal-model CASE.json --out DIR`.
   - Stop if `model_checks_ok` or `workbook_verification.ok` is false.
3. **Stress it before admiring it.** Read the breakevens: the exit multiple for 1.0x, 2.0x and the hurdle; the EBITDA shortfall before a covenant breach and before cash runs out; and the maximum bid.
   - Check the value-creation bridge. A deal that works only through multiple expansion is a market bet, not an operating plan.
4. **Cross-check value.**
   - Compare the offer with the DCF, comps and precedents on the football field.
   - If the exit multiple implies perpetual growth well above nominal GDP, say so.
   - If strategic precedents sit above the sponsor's ability to pay, expect to be outbid rather than chase.
5. **Structure for India.** Work through the memo's structuring section with counsel before relying on it:
   - SAST open offer and delisting thresholds;
   - acquisition-finance rules and Companies Act s.67;
   - the interest-limitation cap and withholding tax.
6. **Take it to IC.** Pass the memo, the workbook and `results.json` to the [investment committee](../india-equity-investment-committee/SKILL.md) skill for an adversarial review.
   - The rule-based recommendation is a floor, not the decision.

## Output

The output is the IC memo, with these rules:
- every number cites `results.json`;
- the workbook is the auditable model;
- all regulatory and tax points are stated as items to confirm, not advice;
- a fictional case keeps its illustrative label.
