# Indian Equity Research & Decision Engine v2.1
Created 12 September 2026 and upgraded through 13 September 2026. This is a reusable research system, not a current stock recommendation or an empirically proven trading strategy.

## Start
Open `SKILL.md` in an assistant with web browsing and file access, or upload this complete folder/archive and instruct it to use the workflow. Read `QUICKSTART.md` for request examples. Skills supply instructions; they cannot grant market-data subscriptions or carry themselves automatically into every future conversation.

> [!WARNING]
> This repository is a research and decision-support harness, not investment advice, a broker, a portfolio manager or a guarantee of returns. It is not SEBI-registered and it does not execute trades. Verify every current fact yourself before risking money.

The package includes an orchestrator, six specialist skills, point-in-time evidence rules, expectations and return-plausibility engines, a multi-layer risk detector, factor and regime analysis, forensic/trap gates, portfolio context, calibration and backtesting standards, scoring and sector guides, a financial formula library, notable-holder verification, material-news analysis, a reusable deep-research prompt, research templates and deterministic calculation helpers. All wording and code here are original. Linked third-party reports are sources, not redistributed assets or permission to redistribute market data.

```mermaid
flowchart TD
 A[Objective and constraints] --> B[Evidence and universe screen]
 B --> C{Horizon}
 C --> D[Trade setup and catalysts]
 C --> E[Business quality and valuation]
 D --> F[Risk register and hard stops]
 E --> F
 F --> J[Skeptical review]
 J --> G{Gates pass?}
 G --> H[Conditional shortlist]
 G --> I[Wait or reject]
```

## File map
- `SKILL.md`: workflow entry point.
- `skills/`: screening, trade research, fundamentals, valuation, risk, skeptical review.
- `references/`: intake, evidence, point-in-time controls, expectations, return plausibility, multi-layer risk detection, factor/regime, forensics, portfolio context, calibration, expert rules, sector overlays, scoring, research sources and validation cases.
- `prompts/deep-stock-research.md`: portable full-research prompt that delays opinion until the evidence, charts, risk register and adversarial review are complete.
- `templates/`: intake, evidence ledger, financial worksheet, shortlist, recommendation, risk register, market context, portfolio map, prediction record, monitoring, backtest report and decision journal.
- `scripts/finance_helpers.py`: transparent arithmetic, not a stock picker or a data collector.
- `scripts/decision_helpers.py`: return, expectations, acceleration, leakage, portfolio risk, market risk, liquidity, calibration and performance diagnostics.
- `references/design-decisions.md`: records which proposed features were included, limited or excluded and why.

## Limits
No connected Indian live feed was tested when this package was created. Public official pages and API documentation were researched. Thresholds, weights, catalyst-freshness classifications and regime labels are configurable research hypotheses, not SEBI requirements or backtested alpha. The included backtest and calibration helpers evaluate supplied point-in-time records; they do not supply a clean historical dataset. Operational and tax rules must be refreshed when used. Research cannot make an equity suitable for a fixed near-term liability simply because it has the highest score.

## Important warnings and limitations

Read these before using the harness with real money:

- **No guaranteed outcome:** A research candidate can lose part or all of its value. The workflow cannot predict prices, eliminate uncertainty or guarantee a stop, target, exit price or maximum loss.
- **Not financial advice:** Outputs are educational research. Suitability depends on your finances, objectives, taxes, legal position and ability to bear loss. Consult a qualified SEBI-registered investment adviser for personal advice.
- **No live-data promise:** The package has no authenticated Indian live feed. Quotes may be delayed, end-of-day or stale. Refresh price, volume, corporate actions, filings, news, taxes, settlement and trading restrictions immediately before acting.
- **Evidence can be incomplete:** A missing, amended, inaccessible or contradictory annual report, result, announcement, ownership record or price series must produce `INSUFFICIENT DATA` or `WATCH`. Never fill gaps with guesses.
- **Point-in-time matters:** Do not use today's universe, financial data or revised filings to claim a historical backtest. Preserve publication and availability timestamps, adjustments and historical index membership.
- **Risk metrics are not worst-case loss:** Volatility, beta, drawdown, historical VaR and CVaR are backward-looking and window-sensitive. Gaps, overnight news, lower circuits, ASM/GSM restrictions, suspensions and illiquidity can create losses larger than the modelled result.
- **Liquidity is conditional:** Days-to-exit estimates depend on traded value and a participation assumption. They are not execution guarantees. Check spread, depth, free float, price bands, circuit history, trade-to-trade, SME status and surveillance measures.
- **Stops can fail:** A stop-loss may execute at a materially worse price or not execute during a gap or locked circuit. For long-term ownership, use thesis and stress-loss limits rather than assuming a tight technical stop.
- **Formulas are fragile:** DCF, reverse DCF, Graham, Altman, Beneish, Piotroski, CAGR and other formulas are diagnostics with domain and accounting limitations. They are not buy signals, and a formula designed for one sector may be invalid for another.
- **Technical analysis is context:** Charts and indicators describe past price and volume behaviour. Moving averages, support, resistance, ATR, relative strength and momentum do not establish business quality or future direction.
- **News and perception are not proof:** Headlines, social posts, analyst commentary, famous-investor references and fund holdings may be stale, indirect, misidentified or already priced in. Verify legal entities and dated primary disclosures. A holder is not an endorsement.
- **No invented consensus:** If analyst estimates, guidance, ownership or a catalyst cannot be verified, report the gap. Do not convert headline counts or sentiment into a probability.
- **Sizing requires context:** Personalized rupee sizing requires capital, current holdings, approved risk limits, liquidity and loss tolerance. Without them, the harness must show formulas and scenarios only. Do not use its illustrative defaults as personal advice.
- **Backtests can mislead:** Supplied backtests are vulnerable to look-ahead bias, survivorship bias, selection bias, missing delisted stocks, execution slippage, costs, taxes and regime change. A passing backtest is not evidence of future alpha.
- **Research is not order authorization:** Do not provide passwords, API keys or session tokens. The workflow does not authorize a broker connection, order placement, leverage or derivatives trade.
- **Current law wins:** SEBI, NSE, BSE, RBI, tax, settlement, margin and corporate-action rules can change. Check the current official rule and your broker's terms before acting.

If any warning changes the decision, the correct outcome is `WATCH`, `REJECT` or `INSUFFICIENT DATA`, not a forced recommendation.

