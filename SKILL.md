---
name: indian-stock-research
description: Run gated institutional-style research on NSE and BSE cash equities for conservative, compounding, tactical, event-driven or asymmetric objectives using point-in-time evidence, market intelligence, forecasts, valuation, risk, IC review and monitoring.
---
# STOCKEX Indian Equity Research OS

Produce an objective-specific, evidence-backed research decision. "Best" means best supported within the stated universe and cutoff, not certain to outperform. The system supports research preparation. It does not execute orders, promise returns or represent a SEBI-registered analyst.

## Intake and outcomes

Read [intake](references/intake.md) and select one mandate: capital preservation, long-term compounding, tactical swing, event driven or asymmetric speculation. Record objective, horizon, loss capacity, liquidity need, exclusions, capital and holdings. Unknown capital or holdings blocks personalized sizing, not conditional research.

An extreme target such as 100% in two months is a search objective. Route it to asymmetric speculation, run [return plausibility](references/return-plausibility.md), require capped capital at risk and accept that no candidate may qualify.

Research statuses: `RESEARCH CANDIDATE`, `SPECULATIVE RESEARCH CANDIDATE`, `WATCH`, `REJECT`, `SCREEN ONLY`, `INSUFFICIENT DATA`.

IC actions: `APPROVE FOR CONSIDERATION`, `APPROVE WITH CONDITIONS`, `RETURN FOR WORK`, `VETO`.

## Fifteen-stage contract

1. **Mandate:** freeze objective, horizon, loss and liquidity constraints.
2. **Universe:** use [screening](skills/india-equity-screen/SKILL.md) and preserve inclusion and exclusion logic.
3. **Evidence room:** use [evidence-room](skills/india-equity-evidence-room/SKILL.md), [evidence gates](references/evidence-gates.md) and [point-in-time rules](references/point-in-time.md). When a STOCKEX database is supplied, require a stable security identity (security ID or ISIN) and a user-specified cutoff timestamp, then generate the point-in-time packet before analysis:

   ```text
   python -m stockex.cli packet DATABASE SECURITY_ID --cutoff TIMESTAMP
   ```

   Route integrity interpretation to the evidence-room contract. When no database exists, preserve the manual primary-source evidence ledger and contradiction workflow. Missing controlling evidence forces `INSUFFICIENT DATA`, `WATCH` or `REJECT`.
4. **World and market map:** use [market intelligence](skills/india-equity-market-intelligence/SKILL.md) and [world-to-stock transmission](references/world-to-stock-transmission.md). Include external drivers only when a material transmission path exists.
5. **Price-move attribution:** explain material rises and falls relative to a broad benchmark, sector and peers. Preserve `UNEXPLAINED` residuals and never infer causality from headline timing alone.
6. **Business and industry:** route multi-year ownership to [fundamental research](skills/india-fundamental-research/SKILL.md). Map economics, competition and [company relationships](references/relationship-graph.md).
7. **Financial normalization:** reconcile filings using [financial normalization](references/financial-normalization.md), sector overlays and applicable [formula diagnostics](references/formulas.md).
8. **Expectations and variant:** use [variant perception](skills/india-equity-variant-perception/SKILL.md). Compare sourced consensus or reverse expectations with an independent driver forecast.
9. **Forecast and valuation:** use [forecast policy](references/forecast-policy.md) and [valuation](skills/india-equity-valuation/SKILL.md). Build coherent bear, base and bull cases. Do not invent probabilities.
10. **Market structure:** route days-to-months work to [swing research](skills/india-swing-research/SKILL.md). Use actual dated charts, price, volume, delivery and liquidity data.
11. **Risk and forensics:** use [risk](skills/india-equity-risk/SKILL.md), [risk detection](references/risk-detection.md), [forensics](references/forensics-and-traps.md) and [legal-credit intelligence](references/legal-credit-intelligence.md). Hard stops remain independent.
12. **Catalysts:** use [catalyst underwriting](references/catalyst-underwriting.md). A catalyst must change expectations, economics, risk or share demand.
13. **Decision and sizing:** compare a diversified benchmark and strongest alternative using [portfolio and opportunity cost](references/portfolio-and-opportunity-cost.md). Use [execution simulation](references/execution-simulation.md). Size only with complete inputs.
14. **Adversarial IC:** use [investment committee](skills/india-equity-investment-committee/SKILL.md). A separate skeptical pass can return, condition or veto the case.
15. **Monitoring and learning:** use [thesis monitor](skills/india-equity-thesis-monitor/SKILL.md), freeze the prediction record and define [active triggers](references/active-research-triggers.md).

## Evidence and tool rules

Use fresh primary disclosures and timestamped market data. Check which tools work before relying on them. Record publication and availability times, amendments, units, consolidated or standalone basis and source limitations. Treat management, analysts, news, social discussion and notable holders as claims or perception evidence until verified. A famous holder cannot override price, governance, liquidity or mandate gates.

Charts require actual adjusted data and labeled dates. Never fabricate a chart, consensus, investor position, interview or real-time feed. A tool failure is a gap, not negative evidence. Check current SEBI, NSE, BSE, RBI, tax, settlement and surveillance rules at use time.

## Required artifacts

For full research complete the mandate, universe log, [evidence packet](templates/evidence-packet.md), [source ledger](templates/source-ledger.md), [world exposure map](templates/world-exposure-map.md), [price attribution](templates/price-move-attribution.md), normalized model, expectations map, catalyst calendar, risk register, valuation, portfolio and execution comparison, [initiating coverage report](templates/initiating-coverage-report.md), [IC memo](templates/investment-committee-memo.md), [prediction record](templates/prediction-record.md) and monitoring record.

Use [the deep-research prompt](prompts/deep-stock-research.md) for a portable full investigation. Use `scripts/decision_packet.py` to validate structure and gate consistency. Calculation helpers are transparent diagnostics and do not collect data or choose stocks.

## Final decision standard

Lead with the research status and IC action. State the variant, what must be true, what is priced in, why the stock moved, scenario reward and downside, strongest bear case, risk posture, execution limits, superior alternatives, conditions, invalidation and next review. Cite material facts beside the claim. Separate facts, calculations, assumptions and inferences.

No obligation to pick a stock. Do not convert a failed trade into a long-term thesis, average away a blocker or make the user's desired return the base case.
