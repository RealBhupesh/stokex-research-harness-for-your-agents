---
name: india-equity-valuation
description: Build sector-appropriate Indian equity valuation ranges with explicit drivers, peer comparisons and downside scenarios.
---
# India Equity Valuation

Read ../../references/sectors.md, evidence.md and expectations.md. Use current source-backed price, diluted shares, financial basis, net debt bridge and relevant peer definitions. Choose methods for business economics, not because a DCF always looks sophisticated.

For nonfinancials: FCFF DCF with WACC, or FCFE with cost of equity, never mixed. FCFF = EBIT*(1-tax)+D&A-capex-change in operating working capital. EV becomes common equity only after net debt, nonoperating assets, minority interests and other claims are reconciled. Avoid double-counting holdings, leases or debt. Use sustainable terminal growth below discount rate and explicit terminal reinvestment/return assumptions. Show terminal value share and sensitivity to growth, margins, WACC and exit multiples.

For banks/NBFC: P/B linked to sustainable ROE, residual income or equity cash flow with capital constraints. For holdings/realty, use justified SOTP/NAV with leakage. Compare compatible peers using normalized forward or trailing periods; label estimates and never manufacture consensus.

Build bear/base/bull drivers before target ranges. Do not imply scenario probabilities are statistical unless estimated from a defensible model. Show upside/downside from the same as-of price and horizon, dilution and dividends consistently. Reverse valuation: identify the growth/margin/return assumptions required by market price and test their plausibility. A “margin of safety” discount is a chosen policy, not a guarantee.

Use ../../scripts/finance_helpers.py only for simple deterministic DCF arithmetic; supply precomputed FCFF and correctly reconciled bridge. The helper does not build forecasts. Record formulas and source cells in ../../templates/financial-worksheet.md.
