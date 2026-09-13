# Deep Indian stock research prompt

Copy the prompt below and replace the bracketed fields. Attach the complete workflow folder or archive in the same conversation.

```text
Use the attached Indian Stock Research & Decision Engine as the controlling workflow.

Research: [company name, NSE/BSE symbol or ISIN]
Objective: [wealth creation / swing trade / income / capital preservation / compare alternatives]
Horizon: [days, months or years]
Capital available: [amount or unknown]
Maximum tolerable loss: [rupees and/or percent]
Current holdings and weights: [list or unknown]
Exclusions or constraints: [no leverage, sectors, liquidity, ethical constraints, etc.]
As-of time: [now or a specified timestamp]

Do not begin with a recommendation and do not force a BUY. First build a complete, timestamped evidence packet, run the risk detector and perform a skeptical review. Form an independent opinion only after these steps. If controlling evidence is missing, return INSUFFICIENT DATA and list exactly what is needed.

1. Verify identity and point-in-time data
- Confirm legal issuer name, ISIN, listing symbol, exchange, security series and corporate-action-adjusted history.
- State the exact quote, exchange timestamp, retrieval time and whether it is live, delayed or end-of-day.
- Freeze an as-of timestamp. Exclude information that was unavailable at that time.
- Record every material source in the source ledger with document date, period, page/table, units, consolidated/standalone basis and confidence.

2. Build the primary-source filing packet
- Read the latest annual report in full, including accounting policies, notes, segment disclosures, auditor report, contingent liabilities, related-party transactions, debt, remuneration, dilution and subsequent events.
- Review at least five financial years when available and the latest eight quarters, including results, cash-flow data and investor presentations.
- Read all material NSE/BSE announcements since the last annual report, later amendments, shareholding patterns, promoter pledges/encumbrances, insider disclosures, bulk/block deals, corporate actions, credit-rating releases and material litigation/regulatory notices.
- Use issuer presentations and concalls as management claims. Reconcile them to audited or exchange-filed evidence.
- Prefer NSE, BSE, SEBI, MCA, RBI, credit-rating agencies and issuer investor-relations documents. Use secondary sources for discovery and independent context, not as authority for a material filing fact.

3. Understand the business and financial engine
- Explain segments, customers, suppliers, geography, capacity, unit economics, cyclicality, competitive position and capital allocation.
- Reconstruct revenue, margins, PAT, EPS, CFO, capex, free cash flow, working capital, ROIC/ROE, debt, dilution and per-share value. Reconcile reported, normalized and estimated numbers.
- Identify what is structural, cyclical, acquisition-driven, accounting-driven or a base effect.
- Apply only relevant formulas from the workflow. Show inputs, units, periods, calculations, applicability and limitations. Formulas are diagnostics, not automatic signals.

4. Map market perception and competing narratives
- Present the strongest evidence-backed bullish thesis, bearish thesis and neutral explanation.
- Identify management guidance, observable market expectations and price-implied expectations. Do not invent analyst consensus.
- Verify notable institutional, promoter, insider or famous-investor involvement using dated primary disclosures and exact legal vehicles. Separate direct holdings from fund holdings, stale positions and media claims.
- Explain recent price/volume behavior and which events appear priced in, disputed, ignored or misunderstood.
- Search independent reporting and credible market commentary for controversies and counterevidence. Label every perception as sourced fact, attributed opinion or inference.

5. Produce charts from actual adjusted data
- Show a five-year weekly chart, or full history if shorter, and a one-year daily chart with price and volume.
- Add 20, 50 and 200-session moving averages where enough history exists, relative performance versus Nifty 50 and a relevant sector index, drawdown, volatility/ATR and evidence-based support/resistance zones.
- Annotate results, guidance changes, capital raises, large corporate actions and other material events.
- State data source, adjustment method and last observation on every chart. Never fabricate a chart or infer a technical signal from unavailable data.
- Use technical analysis as timing and risk context. It cannot override business, valuation, governance or liquidity evidence.

6. Analyze news and catalysts
- Build a deduplicated event ledger for [12 months unless the horizon requires another period]. Separate occurrence date from publication date.
- Link every material event to revenue, margin, cash flow, balance sheet, dilution, cost of capital, valuation or trading liquidity.
- Scale contracts, orders, capex and legal exposures relative to company size. Mark unverified, stale, recurring and already-priced information.
- List dated upcoming catalysts and what observable result would confirm or invalidate each one.

7. Value the equity and expose expectations
- Use methods suitable to the sector and business economics, with bear, base and bull ranges. Do not use a DCF mechanically for businesses where another framework is more defensible.
- Reconcile enterprise value to common equity, net debt, minorities, investments, options/warrants and diluted shares.
- Show sensitivity to the assumptions that matter most and calculate returns from the same timestamped market price.
- Run reverse valuation to identify the growth, margin, ROE or terminal assumptions embedded in the current price. Compare those expectations with historical evidence, capacity and industry reality.

8. Run the multi-layer risk detector
- Complete the workflow risk register across evidence, business, accounting, solvency, governance, valuation, market, liquidity, event, macro, portfolio and mandate risks.
- Check audit issues, receivables/inventory, cash conversion, related parties, pledge, dilution, refinancing, contingencies, ASM/GSM, trade-to-trade, SME status, price bands, circuits, free float and exit capacity.
- Calculate backward-looking volatility, beta, maximum drawdown, downside deviation and historical VaR/CVaR with stated windows. Explain that these are not maximum-loss estimates.
- Estimate normal and stressed days-to-exit using position value, traded value and an explicit participation cap.
- Run coherent company, sector/macro and market/liquidity stress scenarios. Do not average away a blocker.
- Assign ACCEPTABLE, ELEVATED, HIGH or UNUNDERWRITABLE risk posture and show the evidence that would change it.

9. Perform an adversarial review before deciding
- Try to disprove each thesis pillar using the strongest contradictory evidence.
- Recheck identity, timestamps, amendments, units, cash-flow reconciliation, dilution, formula inputs, valuation bridge, holder claims, event dates, chart dates and portfolio concentration.
- Rank review findings as BLOCKER, MATERIAL or MINOR. Fix them or carry them visibly into the result.

10. Form the independent opinion
- Return only RESEARCH CANDIDATE, WATCH, REJECT, SCREEN ONLY or INSUFFICIENT DATA.
- Lead with a one-sentence opinion tied to my objective and horizon. Separate fact, assumption and inference.
- Compare at least three relevant peers and a diversified benchmark alternative when appropriate.
- State what must be true, what appears priced in, the strongest bear case, top failure paths, valuation range, conditional entry or wait conditions, invalidation, monitoring triggers and next review date.
- Give personalized position size or share count only if capital, holdings, liquidity and approved risk limits are known. Otherwise provide formulas and scenarios only.
- Cite every material factual claim beside the claim. Include limitations and unresolved evidence conflicts.
- Do not promise returns, claim certainty, fabricate consensus or holders, treat headlines as proof, or execute an order.
```
