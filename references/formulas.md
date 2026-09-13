# Financial formula library

Formulas are compact lenses. They do not predict price reliably by themselves. Use source-linked consolidated or standalone inputs consistently, state fiscal periods and units, and apply sector exclusions. Never average unrelated formula outputs into a fake probability of success.

## Core return and valuation formulas

| Formula | Definition | Use | Critical limitation |
|---|---|---|---|
| CAGR | `(ending / beginning)^(1 / years) - 1` | Multi-year revenue, EPS, book value or price growth | Invalid for nonpositive endpoints; hides volatility and dilution |
| ROE | `PAT attributable to common equity / average common equity` | Equity profitability | Leverage, buybacks and a small equity base can inflate it |
| ROIC | `NOPAT / average invested capital` | Operating return against capital employed | Define NOPAT, goodwill, leases and excess cash consistently; not for banks |
| DuPont ROE | `net margin × asset turnover × financial leverage` | Explains why ROE changed | Accounting definitions and financial-sector balance sheets need adaptation |
| FCF yield | `normalized free cash flow to equity / market capitalization` or `FCFF / enterprise value` | Compares cash economics with price | State numerator/denominator pairing; cyclic peaks distort it |
| Earnings yield | `normalized EPS / price` | Inverse P/E comparison | Earnings quality and cycle matter |
| PEG | `P/E / expected EPS growth rate in percentage points` | Rough growth-price sense check | Forecast-sensitive, inconsistent when growth is negative or unstable; not intrinsic value |
| Graham number | `sqrt(22.5 × EPS × BVPS)` | Historical conservative heuristic for positive EPS/BVPS | Not designed for asset-light, high-growth, financial, negative-input or modern franchise analysis |
| DCF terminal value | `FCF_(n+1) / (discount rate - perpetual growth)` | Values post-forecast cash flows | Requires `r > g`; often dominates value, so show sensitivity and terminal share |

Use ROIC relative to a defensible cost of capital and evaluate reinvestment runway. Use normalized earnings and diluted shares. Historical price returns must be corporate-action adjusted; total return includes distributions.

## Piotroski F-score, 0 to 9

Use the original nine binary signals primarily as a financial-strength diagnostic for high book-to-market nonfinancial firms, the context studied by Joseph Piotroski. It is not a universal quality score.

Award one point for each, using consistent annual periods:

1. Positive return on assets.
2. Positive cash flow from operations.
3. Higher ROA than the prior year.
4. CFO greater than net income, with matched scaling.
5. Lower long-term debt to average assets than the prior year.
6. Higher current ratio than the prior year.
7. No increase in shares outstanding, adjusted for splits and similar actions.
8. Higher gross margin than the prior year.
9. Higher asset turnover than the prior year.

Do not force this on banks, insurers or companies lacking comparable line items. Record each bit and source, not only the total.

## Altman Z-score, original public-manufacturing form

`Z = 1.2(WC/TA) + 1.4(RE/TA) + 3.3(EBIT/TA) + 0.6(MVE/TL) + 1.0(Sales/TA)`

Here WC is working capital, TA total assets, RE retained earnings, MVE market value of equity and TL total liabilities. The original model was developed using a particular US manufacturing sample. Do not apply its published cutoffs blindly to Indian, service, financial, young or private firms. Treat the result as a distress screen, not a bankruptcy probability or valuation. Name the precise variant when using Z-prime or Z-double-prime.

## Beneish eight-variable M-score

`M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI + 4.679 TATA - 0.327 LVGI`

Use two comparable annual periods and document the Ind AS line-item mapping:

- `DSRI = (receivables / sales)_t / (receivables / sales)_(t-1)`.
- `GMI = gross margin_(t-1) / gross margin_t`, where gross margin is gross profit divided by sales.
- `AQI = [1 - (current assets + net PPE) / total assets]_t / the same measure_(t-1)`.
- `SGI = sales_t / sales_(t-1)`.
- `DEPI = [depreciation / (depreciation + net PPE)]_(t-1) / the same rate_t`.
- `SGAI = (SG&A / sales)_t / (SG&A / sales)_(t-1)`.
- `LVGI = [(current liabilities + long-term debt) / total assets]_t / the same ratio_(t-1)`.
- `TATA = (income from continuing operations - operating cash flow) / total assets_t`.

A score above the commonly cited original cutoff near `-1.78` is a forensic flag for closer investigation, not a finding of fraud. Restatements, acquisitions, accounting changes, zero denominators and sector economics can create false or undefined signals. Explain which components drive the result and verify the underlying notes. If Indian statements do not disclose a comparable SG&A or gross-profit line, mark the diagnostic unavailable rather than fabricating a mapping.

## Momentum and risk formulas

- Total return: `(adjusted ending value + distributions - adjusted beginning value) / adjusted beginning value`.
- Relative return: stock total return minus the same-date benchmark total return.
- Annualized volatility: standard deviation of periodic log returns multiplied by the square root of periods per year. State frequency and window.
- Maximum drawdown: largest peak-to-trough decline in the observed series.
- True range: maximum of `high-low`, `abs(high-prior close)`, `abs(low-prior close)`. State ATR smoothing and period.
- Reward/risk: expected gain to target divided by planned loss to invalidation after estimated friction. This is not expectancy.
- Expected value, only with defensible probabilities: `sum(probability_i × payoff_i)`. Label subjective scenario probabilities.

The Nifty200 Momentum 30 methodology uses 6- and 12-month returns adjusted for volatility. That supports momentum as a research dimension, not a claim that the same construction predicts a two-month winner.

## Formula selection

Use at least one business-return lens, one cash-quality lens, one valuation lens and one downside lens when applicable. More formulas do not create more truth. A failed governance, evidence or liquidity gate cannot be rescued by an attractive ratio. Cite the original academic or authoritative methodology from `research-sources.md` when a named formula materially affects the decision.
