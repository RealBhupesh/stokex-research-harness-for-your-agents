---
name: indian-stock-research
description: Screen, compare, and research NSE and BSE stocks against an investor objective, with distinct short term trade and long term investment workflows, verified evidence, valuation, and risk controls.
---
# Indian stock research
Produce an objective-specific, evidence-backed shortlist and conditional research recommendation. Best means best supported within the screened universe at a stated time, not best across all Indian stocks or certain to outperform. This skill supports research and decision preparation; it does not execute orders or claim SEBI registration.

## Run contract
1. Read [intake](references/intake.md). Resolve objective, horizon and loss tolerance. Unknown capital or holdings does not block a research shortlist, but blocks personalized share counts and suitability conclusions. Record assumptions, never infer wealth from past conversations.
2. Read [evidence](references/evidence.md), [point-in-time rules](references/point-in-time.md), [market constraints](references/india-constraints.md), and [tools](references/tools.md). Check which tools actually work. Retrieve fresh primary disclosures and timestamped market data. Missing essential inputs produce SCREEN ONLY or INSUFFICIENT DATA, never invented facts.
3. Run [return plausibility](references/return-plausibility.md) before searching when the user's required return is extreme for the horizon. Route to [screening](skills/india-equity-screen/SKILL.md), then [short term](skills/india-swing-research/SKILL.md) for days to months or [long term](skills/india-fundamental-research/SKILL.md) for multi-year ownership. A 6 to 24 month mandate needs both valuation and a catalyst/time-bound reassessment.
4. Use [valuation](skills/india-equity-valuation/SKILL.md) for long term and materially valuation-dependent trades. Apply [risk](skills/india-equity-risk/SKILL.md) using the [multi-layer risk detector](references/risk-detection.md). Read [expert rules](references/expert-rules.md), the applicable [sector overlay](references/sectors.md), and [formula library](references/formulas.md). Formulas are diagnostics with domain limits, not automatic buy signals.
5. Read [expectations](references/expectations.md) for valuation-dependent decisions. Read [factors and regime](references/factors-and-regime.md) for screens or trades and [forensics and traps](references/forensics-and-traps.md) for every single-stock recommendation.
6. Read [ownership signals](references/ownership.md) when the user asks who owns or invested in a company. Read [news and events](references/news.md) for every current recommendation. A notable holder or positive headline cannot override price, evidence, governance, liquidity, or mandate gates.
7. Apply [portfolio context](references/portfolio-context.md) when holdings are known. Complete the [risk register](templates/risk-register.md), including hard stops, coherent stress scenarios and exit capacity. Perform [review](skills/india-equity-review/SKILL.md) as a separate pass. It is a reasoning role, not a requirement to spawn agents. Do not hide a failed gate behind a high score.
8. Fill [recommendation](templates/recommendation.md), [source ledger](templates/source-ledger.md), [market context](templates/market-context.md), and [monitoring](templates/monitoring.md). For a forward-looking decision, also create a frozen [prediction record](templates/prediction-record.md) and later score it using [validation and calibration](references/validation-and-calibration.md). Lead with the decision, compare alternatives, include downside, entry conditions and thesis invalidation. Charts require actual data and labeled dates; never fabricate charts. Use [the deep-research prompt](prompts/deep-stock-research.md) when the user requests a full single-stock investigation or wants a portable prompt.

## Outcomes
RESEARCH CANDIDATE: evidence and analysis support further decision-making within the stated mandate.
WATCH / WAIT: merits exist but price, trigger, risk or evidence is inadequate.
REJECT: fails mandate or hard constraints.
SCREEN ONLY: preliminary candidate, not an actionable recommendation.
INSUFFICIENT DATA: missing controlling evidence prevents the decision.

No obligation to pick a stock. No guaranteed returns, fake consensus, implied real-time feed, fabricated analyst interviews, unattributed famous-investor claims, headline-count sentiment, or conversion of a failed trade into a long term thesis. Read only mode-specific references needed for the run. User-requested depth and exclusions override configurable defaults, not evidence integrity.
