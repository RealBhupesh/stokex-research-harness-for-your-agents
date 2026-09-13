# Factor interactions and market regime

Factors rank comparable securities at a common as-of date. They do not prove causality or suitability.

## Factor families

- Momentum: corporate-action-adjusted 6- and 12-month return, volatility-adjusted momentum, relative strength versus the same-date broad and sector benchmarks.
- Quality: sector-appropriate returns on capital, cash conversion, earnings stability, leverage/service capacity and incremental returns.
- Value/expectations: normalized earnings or FCF yield, sector-appropriate multiples, reverse valuation and downside.
- Growth/revisions: revenue/EPS acceleration, margin direction, order/capacity conversion and properly sourced estimate revisions.
- Risk/execution: volatility, drawdown, liquidity, free float, surveillance/circuit constraints and balance-sheet stress.

Avoid redundant double counting. P/E and earnings yield are the same information; multiple momentum windows are correlated. Standardize within a defensible sector/universe, winsorize only with a documented rule, retain raw values, and calculate ranks using only point-in-time observations.

Use interaction flags rather than blindly averaging everything:

| Interaction | Interpretation to test |
|---|---|
| Strong momentum + accelerating earnings + adequate liquidity | Confirm whether fundamentals support repricing |
| Strong momentum + deteriorating cash/earnings | Crowding or narrative risk; require stronger catalyst evidence |
| Low valuation + worsening balance sheet | Possible value trap |
| High quality + extreme implied expectations | Good company, potentially poor entry |
| Positive catalyst + weak execution/liquidity | Event may not be safely tradeable |

## Earnings acceleration

Compare quarterly year-over-year growth using at least eight comparable quarters. Acceleration is the change in YoY growth, not QoQ seasonality. Reconcile acquisitions, exceptional items, tax rates, dilution and base effects. Mark acceleration low confidence when the prior-year base is near zero or negative. Use revenue, EBITDA/margin, PAT and diluted EPS separately; do not collapse them into one number.

## Regime overlay

Observe trend, breadth, India VIX, rates/yields, INR, oil/commodity exposure, FPI/DII activity, market-cap relative strength and sector breadth using dated official or licensed data. Describe the regime as a scenario and list conflicting signals. Do not give the regime a numeric probability without a calibrated model.

Business quality stays unchanged by a daily regime label. Regime can alter trade timing, discount rates, scenario weights, liquidity assumptions and position limits. FPI/DII aggregate flow is context, not a causal signal for a particular stock. India VIX reflects option-implied expected volatility over its stated horizon, not a direction forecast.
