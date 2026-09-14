# STOCKEX v3 deep Indian stock research prompt

Copy the prompt, replace the bracketed fields and attach the complete repository or archive.

```text
Use the attached STOCKEX Indian Equity Research OS as the controlling workflow.

Company, NSE/BSE symbol or ISIN: [value]
Objective: [capital preservation / long-term compounding / tactical swing / event driven / asymmetric speculation]
Desired outcome: [return or goal]
Horizon: [days, months or years]
Capital: [amount or unknown]
Maximum tolerable loss and drawdown: [rupees, percent or unknown]
Total loss of allocated speculative capital acceptable: [yes / no / not applicable]
Current holdings and weights: [list or unknown]
Liquidity, sector, ethical or instrument constraints: [value]
Research cutoff: [now or exact timestamp]

Do not begin with an opinion and do not force a BUY. Complete the evidence, attribution, forecast, risk and IC gates first. If controlling evidence is missing, return INSUFFICIENT DATA and name the missing evidence.

1. Freeze the mandate and universe
- Confirm objective, horizon, loss capacity, liquidity need and exclusions.
- Treat an extreme desired return as a search objective, not a base-case forecast.
- Define the investable universe, benchmark, peer logic, exclusions and research cutoff.
- Preserve every screened candidate. Do not narrow the universe after seeing the winner.

2. Build the point-in-time evidence room
- Confirm legal issuer, ISIN, symbol, exchange, series and corporate actions.
- Record quote timestamp, retrieval time and live, delayed or end-of-day status.
- Read the annual report including notes and auditor report, at least five years and eight quarters when available, and material subsequent NSE/BSE filings.
- Review results, shareholding, pledges, insider disclosures, bulk/block deals, ratings, litigation, regulatory notices, amendments and corporate actions.
- Record source ID, publisher, URL, period, publication time, availability time, page or table, units, consolidated or standalone basis, fact or inference and limitations.
- Build a contradiction ledger. Exclude information unavailable at the cutoff.

3. Map the world to the stock
- Test global growth, rates, yields, liquidity, INR and relevant currencies, commodities, power, freight, Indian macro conditions, fiscal and regulatory policy, geopolitics, trade, technology, weather, industry capacity, inventories, competitors, verified flows and company events.
- Include a driver only when it has an evidenced path into revenue, costs, assets, liabilities, financing, valuation, risk perception, liquidity or share demand.
- For each material driver state current condition, exposure, transmission path, lag, magnitude range, countervailing force, affected forecast line, confidence and source IDs.
- Mark unrelated developments NOT MATERIAL.

4. Explain why the stock is rising or falling
- Define the exact adjusted price window.
- Compare total return with a broad benchmark, sector index and explicit peer basket.
- Inspect volume, delivery, spread, volatility, gaps, circuits and liquidity.
- Build a timestamped filing, news and macro-event timeline.
- Test market, sector, factor, flow, technical and company-specific explanations.
- Use peers, suppliers and customers as counterfactual evidence where valid.
- Explain what changed in earnings expectations, discount rate, perceived risk or share supply-demand.
- Label every proposed cause CONFIRMED, STRONGLY SUPPORTED, PLAUSIBLE or UNEXPLAINED. Preserve unexplained residuals.

5. Understand the business, industry and relationship graph
- Explain segments, products, customers, suppliers, geography, capacity, unit economics, cyclicality, competitive advantage and disruption risk.
- Compare relevant peers on business drivers and economics, not only valuation multiples.
- Map promoters, subsidiaries, associates, joint ventures, customers, suppliers, lenders, rating agencies, competitors and regulators using verified legal entities.
- Identify concentration, related parties, guarantees, cross-holdings and economic dependencies.

6. Normalize financial history
- Reconcile revenue, margins, PAT, EPS, CFO, capex, free cash flow, working capital, debt, dilution, ROIC or ROE and sector KPIs.
- Keep reported and normalized figures side by side with source-backed adjustments.
- Inspect exceptional items, capitalized costs, acquisitions, subsidies, FX, leases, receivables, inventory, contingent liabilities and related parties.
- Use sector-specific analysis for banks, NBFCs, insurers, cyclicals and asset-heavy businesses.
- Apply formulas only inside their valid accounting and sector domains. Show inputs, periods, units and limitations.

7. Audit management credibility
- Freeze dated guidance, capacity promises, acquisition claims, deleveraging goals, dilution statements and capital-allocation commitments.
- Compare each promise with the actual outcome on the original deadline and basis.
- Separate external shocks from controllable execution.
- Track optimism bias, changing definitions, selective KPIs and recurring exceptional items.

8. Build driver forecasts and variant perception
- Forecast operating KPIs, revenue, margins, working capital, capex, financing, tax, dilution and cash flow from explicit drivers.
- Record driver ranges, source or derivation, historical base, correlation and disconfirming indicator.
- Track estimate vintages and explain every revision.
- Compare the independent forecast with sourced consensus or clearly labeled reverse-valuation expectations.
- State what the market appears to believe, how the independent view differs, why the difference exists and what would disprove it.

9. Build scenarios and valuation
- Create internally consistent bear, base and bull financial statements and valuation ranges.
- Use at least two suitable methods when the business permits and reconcile differences.
- Bridge enterprise value to common equity, net debt, minorities, investments, options, warrants and diluted shares.
- Show sensitivities and returns from the same timestamped price.
- Use probabilities only when explicitly supported and make them sum to 100%. Otherwise show ranges without expected value.
- Run reverse valuation and state when terminal value, exit multiples or commodity assumptions dominate.

10. Underwrite catalysts
- For every catalyst state event window, affected market belief, evidence, leading indicators, positive/base/negative interpretation, what is priced in, delay rule and failure mode.
- Build an event tree for success, partial success, delay and failure.
- Connect each branch to forecasts, valuation, liquidity and downside.
- Reject time-bound ideas without a plausible recognition mechanism.

11. Produce technical and market-structure evidence
- Create a five-year weekly and one-year daily chart when data permits, using adjusted price and volume.
- Show relevant moving averages, benchmark and sector relative strength, drawdown, volatility or ATR and evidence-based support and resistance.
- Annotate results, guidance, financing and material events.
- State source, adjustment and last observation on every chart. Never fabricate charts.
- Use technical evidence for timing, positioning and risk, never to override governance or valuation.

12. Run risk, forensic, legal and credit checks
- Complete mandate, evidence, accounting, governance, business, balance-sheet, legal, regulatory, market, factor, liquidity, valuation, catalyst, portfolio, execution and model risks.
- Check auditors, cash conversion, receivables, inventory, related parties, promoter pledge, dilution, refinancing, defaults, guarantees, ratings, court or IBBI matters, contingencies and group exposure.
- Check free float, ASM/GSM, SME or trade-to-trade status, bands, circuits and normal and stressed exit capacity.
- Calculate descriptive volatility, beta, drawdown, downside deviation and historical VaR/CVaR with stated windows and limitations.
- Run coherent company, macro-sector and liquidity stresses. Do not average away a hard stop.

13. Compare alternatives, portfolio fit and execution
- Compare the candidate with cash or a suitable low-risk alternative, a diversified Indian benchmark and the strongest peer using the same horizon and assumptions.
- Show before-and-after sector, factor, commodity, currency, promoter-group and catalyst concentration when holdings are known.
- Estimate spread, slippage, fees, taxes, participation capacity and entry and exit sessions.
- Size only from complete portfolio, loss-budget, cash, concentration and liquidity inputs. Otherwise show formulas.

14. Perform an independent adversarial IC review
- Try to disprove every thesis pillar and challenge what is already priced.
- Recheck identity, timestamps, units, normalization, forecasts, valuation bridge, holder claims, catalysts, legal-credit exposure, liquidity and alternatives.
- Rank findings BLOCKER, MATERIAL or MINOR and preserve dissent.
- Return only APPROVE FOR CONSIDERATION, APPROVE WITH CONDITIONS, RETURN FOR WORK or VETO.
- Never let a score override a failed gate or unresolved controlling contradiction.

15. Form, freeze and monitor the opinion
- Return RESEARCH CANDIDATE, SPECULATIVE RESEARCH CANDIDATE, WATCH, REJECT, SCREEN ONLY or INSUFFICIENT DATA.
- Lead with a one-sentence objective-specific conclusion and IC action.
- State variant perception, what must be true, what appears priced, price-move attribution, scenario reward and downside, strongest bear case, hard risks, opportunity cost, execution limits, conditions and invalidation.
- Freeze the evidence cutoff, forecast ranges, probabilities, price, catalysts, risks, decision, model version and packet hash.
- Define active triggers, affected stages and next review. Do not claim continuous monitoring without a configured feed or automation.
- Cite material facts beside each claim. Separate facts, calculations, assumptions and inferences.
- Do not promise returns, fabricate consensus or holders, treat news as proof, or execute an order.
```
