# STOCKEX v3 Institutional Equity Research OS

**Status:** Proposed design for review

**Date:** 13 September 2026

**Scope:** India-listed cash equities on NSE and BSE

**Purpose:** Upgrade the existing research toolkit into a gated, auditable equity-research operating system that behaves like a disciplined senior analyst and investment committee.

## 1. Design objective

STOCKEX v3 must answer a harder question than "which stock scores highest?"

> Given this investor mandate, information set, valuation, market expectations, risks, catalysts and portfolio context, is there a sufficiently supported and actionable variant view?

The system may recommend further research, watching, waiting or rejection. It is never required to produce a buy idea. It must delay its opinion until the evidence packet and all controlling gates are complete.

The target is institutional process quality, not institutional branding. The harness remains research and decision support. It does not represent a SEBI-registered analyst, personalize advice without adequate suitability inputs, execute orders or promise returns.

## 2. Success criteria

The upgrade is successful only if it improves one or more of these decision properties:

1. **Evidence integrity:** every important factual claim is traceable to a dated source and a point-in-time availability record.
2. **Forecast quality:** the analyst states explicit operating forecasts, key drivers, ranges and disconfirming evidence.
3. **Variant perception:** the decision identifies what the market appears to expect, how the independent view differs and why that difference exists.
4. **Valuation discipline:** the thesis connects operating assumptions to scenario values and prospective returns rather than using isolated multiples.
5. **Risk detection:** accounting, governance, balance-sheet, regulatory, liquidity and thesis risks can independently stop the process.
6. **Catalyst discipline:** a mispricing must have a plausible path to recognition or a defined long-duration monitoring logic.
7. **Decision quality:** the final action follows from expected reward, downside, evidence confidence, mandate fit and portfolio fit.
8. **Learning:** forecasts and decisions are frozen, later scored and attributed to process errors instead of rewritten after the outcome.

More prompts, indicators, formulas, famous names or headlines do not count as improvements unless they change one of these properties.

## 3. Non-goals

Version 3 will not:

- claim to scan every Indian security without a defined and reproducible universe;
- infer investor suitability from a ticker request alone;
- provide live prices or real-time alerts without a configured data source;
- use a single opaque score to overrule a hard risk gate;
- convert news sentiment, social-media activity or notable ownership into an endorsement score;
- use a formula outside its accounting or sector domain merely because the input exists;
- fabricate consensus estimates, management access, channel checks, charts or data;
- use post-event or revised information in a historical decision record;
- optimize thresholds on the same observations used to report performance;
- place trades, connect a broker or authorize leverage and derivatives.

## 4. Operating model

The workflow consists of twelve stages. Each stage produces a named artifact and a gate result. A later stage may send the case back for more evidence, but it may not silently fill an earlier gap.

| Stage | Analyst question | Required artifact | Gate |
|---|---|---|---|
| 0. Mandate | What outcome, horizon, loss tolerance and exclusions govern this decision? | Mandate card | `MANDATE_READY` |
| 1. Universe | What investable set was actually considered and why? | Universe definition and screen log | `UNIVERSE_REPRODUCIBLE` |
| 2. Evidence room | Do we have current, primary and point-in-time evidence for controlling claims? | Evidence packet and source ledger | `EVIDENCE_COMPLETE` |
| 3. Business and industry | How does the company make money, defend economics and compare with peers? | Business and industry dossier | `BUSINESS_UNDERSTOOD` |
| 4. Financial normalization | What are sustainable revenue, margins, cash flows, capital needs and balance-sheet risks? | Normalized historical model | `FINANCIALS_RECONCILED` |
| 5. Expectations and variant | What is priced in, what do we believe differently and what evidence can prove us wrong? | Expectations and variant map | `VARIANT_DEFINED` |
| 6. Forecast and valuation | What assumptions produce bear, base and bull values and returns? | Forecast model and valuation bridge | `VALUATION_COHERENT` |
| 7. Market structure | Does price, volume, liquidity and technical structure support the chosen horizon? | Market-structure sheet | `EXECUTION_FEASIBLE` |
| 8. Risk and forensics | What can permanently impair capital, break the thesis or prevent exit? | Risk register and forensic review | `RISK_ACCEPTABLE` |
| 9. Catalysts | What could close the expectation gap, on what timeline and with what evidence? | Catalyst calendar | `CATALYST_CREDIBLE` |
| 10. Decision and sizing | Is the opportunity attractive relative to alternatives and portfolio constraints? | Draft decision memo | `DECISION_SUPPORTED` |
| 11. Adversarial IC | Can an independent skeptic kill the thesis or expose an unresolved contradiction? | IC challenge record | `IC_CLEARED` |
| 12. Monitoring and learning | What signals change the view, and what did the process get right or wrong? | Thesis monitor and frozen prediction record | `MONITORING_ACTIVE` |

### Stage routing

- **Short term, days to months:** emphasize liquidity, technical structure, event timing, expectation revision and gap risk. Fundamentals remain a risk control.
- **Long term, multiple years:** emphasize unit economics, competitive advantage, reinvestment runway, normalized returns on capital, stewardship, valuation and thesis milestones.
- **Medium term, roughly 6 to 24 months:** require the long-term business and valuation work plus a dated catalyst or reassessment path.
- **Screen or compare:** may stop at `SCREEN ONLY`; it cannot inherit the authority of completed single-stock diligence.

## 5. Core research contracts

### 5.1 Mandate card

The minimum mandate is objective, horizon, maximum acceptable loss or drawdown concept, liquidity need, prohibited sectors or instruments, and whether existing holdings are known. Missing capital and holdings allow non-personalized research, but block rupee sizing and suitability claims.

### 5.2 Evidence packet

Every material claim must carry:

- claim identifier;
- source title, publisher and URL or local document reference;
- source class: exchange or regulator, audited filing, company filing, official industry data, market data, reputable secondary analysis, or unverified lead;
- publication date and the date the information became available;
- period covered;
- exact table, page or section where practical;
- extracted fact versus analyst inference;
- corroboration status;
- contradiction or limitation;
- freshness status at the research cutoff.

Controlling claims about financial results, ownership, corporate actions, auditor matters and regulatory events require primary evidence whenever available. Secondary reporting may discover an issue but cannot close the evidence gate on its own.

### 5.3 Normalized financial model

The model must reconcile reported history before forecasting. At minimum it covers revenue drivers, gross or contribution economics where relevant, operating margins, working capital, capex, free cash flow, debt, dilution, contingent liabilities, related-party transactions and sector-specific operating metrics.

Every adjustment must state:

- reported value;
- normalized value;
- reason;
- source;
- whether the adjustment increases or decreases apparent quality;
- whether it is recurring, non-recurring or uncertain.

For banks, NBFCs, insurers and other financial companies, the model uses sector-specific balance-sheet and credit metrics rather than industrial-company free-cash-flow formulas.

### 5.4 Expectations and variant map

The system separates four layers:

1. **Observable facts:** filed results, prices, volumes, guidance and disclosed ownership.
2. **Market-implied expectations:** growth, margins, capital intensity or risk implied by price and available consensus.
3. **Independent forecast:** the analyst's explicit driver-based view.
4. **Variant perception:** the material difference between layers 2 and 3.

Each variant must include its mechanism, magnitude, time horizon, evidence, consensus source or reverse-valuation inference, disconfirming evidence, confidence and catalyst. If no material, defensible difference exists, the correct decision is `WATCH`, `REJECT` or `INSUFFICIENT DATA`.

### 5.5 Scenario and valuation contract

Bear, base and bull cases must use internally consistent operating assumptions. The report shows the bridge from operating drivers to financial statements, valuation and prospective return.

Rules:

- use at least two suitable valuation approaches when the business permits;
- reconcile materially different model outputs instead of averaging them mechanically;
- show sensitivity to the assumptions that dominate value;
- use scenario probabilities only when the analyst explicitly supplies them and they sum to 100%;
- do not disguise uncertainty with decimal precision;
- test return plausibility against the stated horizon, dilution, dividends, costs and downside;
- disclose when a terminal value, exit multiple or commodity assumption dominates the result.

### 5.6 Risk contract

Risk is not the inverse of conviction. The system maintains separate layers for:

- mandate and suitability;
- evidence quality;
- accounting and auditor signals;
- governance, ownership and related parties;
- business model and competitive position;
- balance sheet, refinancing and dilution;
- regulatory, legal, tax and political exposure;
- market, factor and regime exposure;
- liquidity, free float, circuits and surveillance constraints;
- valuation and expectation risk;
- event, operational and execution risk;
- portfolio concentration and covariance;
- model and process risk.

Each risk states evidence, mechanism, leading indicator, likelihood as a range or `UNKNOWN`, severity, mitigant, residual exposure, owner, monitoring frequency and invalidation threshold. Auditor resignation or qualification, unverifiable cash, severe disclosure inconsistency, unresolved promoter encumbrance, material legal uncertainty, impossible exit capacity or missing controlling filings can independently force `REJECT` or `INSUFFICIENT DATA`.

### 5.7 Catalyst contract

A catalyst is a mechanism that can change expectations, not merely a scheduled date. Each catalyst records:

- event and expected window;
- which forecast or market belief it can change;
- leading evidence;
- base, positive and negative interpretation;
- probability only if supported and explicitly estimated;
- likely information path and time to recognition;
- pre-mortem failure mode;
- review trigger if the event is delayed or already priced.

### 5.8 Ownership and market-perception contract

Famous investors, mutual funds, FPIs, insurers and promoter transactions are context, never borrowed conviction. The analyst must verify the exact legal entity, security, reporting period, position size where disclosed, change versus the previous comparable period and source date.

Market perception must distinguish:

- company and exchange disclosures;
- sell-side or rating-agency views;
- credible financial reporting;
- social and retail discussion;
- price and volume behaviour.

The report summarizes competing narratives and tests each against evidence. Headline counts and positive-versus-negative word counts do not become probabilities or recommendation scores.

## 6. Decision policy

The final output uses two layers.

### Research status

- `RESEARCH CANDIDATE`: diligence supports further decision-making within the mandate.
- `WATCH / WAIT`: business or setup has merit, but price, timing, evidence or risk is inadequate.
- `REJECT`: a hard gate fails or expected reward does not justify risk.
- `SCREEN ONLY`: preliminary comparison without completed single-stock diligence.
- `INSUFFICIENT DATA`: controlling evidence is missing, stale or contradictory.

### IC action

- `APPROVE FOR CONSIDERATION`: all required gates pass; any sizing remains conditional on portfolio inputs.
- `APPROVE WITH CONDITIONS`: explicitly named conditions must be satisfied before action.
- `RETURN FOR WORK`: a fixable evidence, model or contradiction gap remains.
- `VETO`: a hard risk or mandate breach makes the case unacceptable.

No aggregate score can convert `VETO`, `REJECT` or `INSUFFICIENT DATA` into approval. Confidence is a statement about evidence and model reliability, not a forecast of investment success.

## 7. Adversarial investment committee

The IC pass is structurally separate from the drafting pass, even when one agent performs both roles. It must test:

1. the strongest bear case and the strongest alternative explanation for recent performance;
2. whether the thesis is already reflected in price;
3. whether normalized earnings are genuinely normalized;
4. whether the catalyst changes economics or only attention;
5. whether management incentives and capital allocation support minority shareholders;
6. whether a liquidity or portfolio constraint invalidates the theoretical return;
7. whether the thesis survives a coherent stress scenario;
8. which single new fact would most likely reverse the decision;
9. whether a cheaper, safer or better-evidenced alternative exists;
10. whether the analyst is anchoring to purchase price, management guidance, a famous holder or a recent chart.

The IC record lists every challenge, response, evidence and unresolved item. Unresolved controlling contradictions block approval.

## 8. Monitoring and learning loop

The system freezes the thesis at decision time. It records forecast distributions or ranges, key drivers, evidence cutoff, price, catalyst dates, risks, invalidation conditions and decision status.

Monitoring classifies new information as:

- confirms thesis;
- weakens thesis;
- invalidates thesis;
- changes valuation only;
- changes timing only;
- changes risk or exit capacity;
- irrelevant noise.

Post-mortems attribute errors to source failure, accounting normalization, industry analysis, forecast, valuation, catalyst timing, technical execution, risk, portfolio fit or decision discipline. Threshold changes require multiple out-of-sample observations and a documented version change. A recent winner or loser does not automatically rewrite the framework.

## 9. Planned repository architecture

The implementation will preserve the current package and add four bounded subsystems.

### Subsystem A: research packet and source control

Planned additions:

- `references/research-operating-system.md`
- `references/evidence-gates.md`
- `references/financial-normalization.md`
- `skills/india-equity-evidence-room/SKILL.md`
- `templates/evidence-packet.md`
- `templates/normalized-financial-model.md`

### Subsystem B: expectations, forecasts and catalysts

Planned additions:

- `references/variant-perception.md`
- `references/forecast-policy.md`
- `references/catalyst-underwriting.md`
- `skills/india-equity-variant-perception/SKILL.md`
- `templates/expectations-variant-map.md`
- `templates/catalyst-calendar.md`

### Subsystem C: decision and investment committee

Planned additions:

- `references/investment-committee.md`
- `skills/india-equity-investment-committee/SKILL.md`
- `templates/initiating-coverage-report.md`
- `templates/investment-committee-memo.md`
- a machine-readable decision-packet schema and deterministic validator;
- tests covering incomplete evidence, hard-stop risk, inconsistent scenarios and prohibited gate overrides.

### Subsystem D: monitoring and analyst calibration

Planned additions:

- `references/thesis-monitoring.md`
- `skills/india-equity-thesis-monitor/SKILL.md`
- `templates/thesis-monitor.md`
- `templates/post-mortem.md`
- tests for frozen records and permitted status transitions.

Existing specialist skills for screening, swing research, fundamental research, valuation, risk and skeptical review will be retained and routed through the new stage contracts. Redundant rules will be consolidated rather than copied into every skill.

## 10. Machine-readable decision packet

The validator will operate on a plain JSON packet using the Python standard library. The initial schema will contain:

- metadata and research cutoff;
- mandate;
- universe definition;
- source ledger and evidence conflicts;
- normalized financial adjustments;
- market expectations and analyst forecasts;
- variant claims;
- scenarios and valuation outputs;
- technical and liquidity observations;
- risk register and hard stops;
- catalysts;
- portfolio constraints;
- stage gates;
- IC challenges and unresolved items;
- research status and IC action;
- monitoring and prediction record references.

The validator checks structure and decision consistency. It does not decide whether a stock is attractive. Examples of deterministic failures include:

- an approval with a failed required gate;
- an approval with unresolved hard-stop risk;
- scenario probabilities that do not sum to 100%;
- a personalized position size without capital and portfolio inputs;
- a current recommendation without a research cutoff or source ledger;
- a famous-holder claim lacking entity, date and primary-source provenance;
- a chart claim lacking dated data;
- a historical record containing a source published after its cutoff.

## 11. Failure and fallback behavior

- Tool failure is recorded. It is never converted into negative evidence.
- A blocked primary source may be substituted only by an equivalent official source or disclosed as a gap.
- Conflicting primary disclosures remain open until reconciled or cause `INSUFFICIENT DATA`.
- Stale price, ownership, surveillance or news data blocks a current action but may permit historical business analysis.
- Missing consensus does not block research. The system may use clearly labeled reverse-valuation inference instead.
- Missing portfolio inputs block personalized sizing, not a conditional research conclusion.
- Unsupported sector formulas are omitted and explained.
- If no candidate passes, the output says so and preserves the screen log.

## 12. Verification strategy

Implementation will follow test-first development for the machine-readable controls.

### Static validation

- all skill metadata passes the skill validator;
- every internal file link resolves;
- `manifest.json` exactly matches the shipped file set and version;
- Markdown lint and JSON parsing pass;
- prohibited claims such as guaranteed returns are absent outside explicit warnings and tests.

### Behavioral cases

At minimum, fixtures will cover:

1. high-quality long-term compounder with expensive expectations;
2. cyclical company near peak margins;
3. bank or NBFC requiring sector-specific analysis;
4. illiquid small cap with strong reported growth;
5. auditor or governance red flag that must veto a high score;
6. event-driven short-term setup with gap risk;
7. notable-investor ownership that must not override fundamentals;
8. positive news already reflected in price;
9. missing primary filing;
10. scenario probabilities and gate statuses that are internally inconsistent.

### Release evidence

A release is complete only after fresh tests, skill validation, repository status review, archive creation, archive-content verification and GitHub verification. Documentation must identify data integrations that were actually tested and those that remain instructions only.

## 13. Delivery sequence

Implementation should proceed in four reviewable increments matching the subsystems above. Each increment updates tests, documentation, the manifest and the orchestrator. This prevents a large prompt rewrite from hiding broken links, conflicting rules or gate regressions.

The final release target is `3.0.0`. Intermediate repository commits may be tagged as implementation phases, but the README must not call the system v3 until all four subsystems pass validation.

## 14. Design rationale and authoritative anchors

The architecture reflects current official and professional research expectations:

- NSE provides official company annual-report, financial-result, announcement and shareholding filing surfaces, supporting the primary-source evidence hierarchy.
- BSE provides official corporate announcement and filing surfaces that can corroborate exchange disclosures.
- SEBI's Research Analyst guidelines and Investor Charter reinforce the need to separate a research-support tool from regulated personalized advice and to use clear risk disclosures.
- CFA Institute's equity-research guidance identifies company and industry analysis, financial forecasts, multiple valuation methods, mispricing, re-rating mechanisms, liquidity, ownership, risk and disclosure footnotes as core report elements.

Source register:

- SEBI, *Investor Charter for Research Analysts*, Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/81, 2 June 2025: https://www.sebi.gov.in/legal/circulars/jun-2025/investor-charter-for-research-analysts_94355.html
- SEBI, *Guidelines for Research Analysts*, Circular SEBI/HO/MIRSD/MIRSD-PoD1/P/CIR/2025/004, 8 January 2025: https://www.sebi.gov.in/legal/circulars/jan-2025/guidelines-for-research-analysts_90634.html
- NSE, *Corporate Filings Annual Reports*: https://www.nseindia.com/companies-listing/corporate-filings-annual-reports
- NSE, *Corporate Filings Financial Results*: https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- NSE, *Corporate Filings Announcements*: https://www.nseindia.com/companies-listing/corporate-filings-announcements
- NSE, *Corporate Filings Shareholding Patterns*: https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern
- BSE, *Corporate Announcements*: https://www.bseindia.com/corporates
- CFA Institute, *Equity Research Report Essentials*, September 2020: https://www.cfainstitute.org/sites/default/files/-/media/documents/support/research-challenge/challenge/rc-equity-research-report-essentials.pdf

## 15. Approval question

Approval of this design means the implementation plan may be written for the four subsystems. It does not approve any stock recommendation, live-data claim or trading integration.
