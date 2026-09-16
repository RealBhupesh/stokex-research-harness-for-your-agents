# Offline point-in-time store

The first executable release is an offline local SQLite evidence store. It
accepts supplied records and does not scrape exchanges or guarantee source
authenticity or completeness. Run these commands from the repository root:

```bash
python -m stockex.cli init research.sqlite3
python -m stockex.cli ingest research.sqlite3 evidence.jsonl
python -m stockex.cli packet research.sqlite3 INE000A01001 --cutoff 2026-06-01T10:00:00+05:30
python -m stockex.cli integrity research.sqlite3
```

The packet is restricted to evidence available at the cutoff. The integrity
report checks internal consistency only, not source authenticity, dataset
completeness or investment suitability.

# Calculation helper
Python standard library only. No credentials, market-data access or orders.

`python3 scripts/finance_helpers.py size /absolute/path/inputs.json`

Sizing inputs: `entry`, `stop`, `risk_rupees`, `cash_cap`, optional `friction_per_share` and `liquidity_share_cap`. Cash cap must already reserve fixed and buy-side charges. Friction is estimated round-trip per share and is included in planned loss. This is long cash-equity sizing, not short selling, derivative margin or guaranteed maximum loss.

`python3 scripts/finance_helpers.py dcf /absolute/path/inputs.json`

DCF inputs: yearly `fcff` array, decimal `discount_rate`, decimal `terminal_growth`, `net_debt`, `diluted_shares`, optional `other_equity_adjustments`. The first flow is one year ahead and all flows are discounted at year end. All monetary values and shares must use compatible scaling. For example, crore rupees divided by crore shares gives rupees per share. Adjustment is a signed common-equity bridge amount, not a second debt subtraction. The simple perpetual model assumes a sustainable final-period FCFF and does not model forecasts or terminal reinvestment itself. Do not use it as an industrial FCFF model for banks.

Additional modes use the same JSON-file interface:

- `cagr`: `beginning`, `ending`, `years`.
- `graham`: `eps`, `book_value_per_share`.
- `altman`: `working_capital`, `retained_earnings`, `ebit`, `market_value_equity`, `total_liabilities`, `sales`, `total_assets`. This is the original public-manufacturing form, not a universal Indian-company formula.
- `beneish`: `dsri`, `gmi`, `aqi`, `sgi`, `depi`, `sgai`, `tata`, `lvgi`. Calculate inputs from the original definitions and matched annual periods.
- `piotroski`: nine named boolean components from `references/formulas.md`, supplied as JSON `true` or `false`.

Outputs include warnings because these formulas are diagnostics. Preserve the full inputs, periods, accounting basis and source IDs beside every result.

## Decision helpers

`python3 scripts/decision_helpers.py MODE /absolute/path/inputs.json`

- `required_return`: `capital`, `target_value`, `calendar_days`.
- `gbm_target_probability`: `start_price`, `target_price`, `years`, `annual_drift`, `annual_volatility`, all rates in decimals. This is a sensitivity model, not a forecast.
- `reverse_fcff_growth`: `current_enterprise_value`, `current_fcff`, integer `years`, `discount_rate`, `terminal_growth`, and optional growth bracket/tolerance. It solves one constant explicit-period growth rate.
- `earnings_acceleration`: at least eight `quarterly_values` in oldest-to-newest order.
- `point_in_time`: `records` containing `available_at` timestamps and a timezone-aware `decision_at`.
- `brier_binary`: matched `probabilities` and binary `outcomes` arrays.
- `portfolio_risk`: portfolio `weights` and a matching covariance matrix whose units determine output periodicity.
- `market_risk_metrics`: matched decimal `periodic_returns` and `benchmark_returns`, plus optional `periods_per_year` and `confidence`, for volatility, beta, drawdown, downside deviation and empirical VaR/CVaR.
- `liquidity_exit_days`: `position_value`, `average_daily_traded_value` and optional `max_participation_rate` to estimate normal or stressed exit sessions.
- `backtest_metrics`: matched decimal `periodic_returns` and `benchmark_returns`, with `periods_per_year` and optional annual risk-free rate. Feed net-of-cost returns when evaluating an implementable rule.

All helpers require clean, source-linked inputs. They do not fetch data, estimate parameters, classify a market regime, or prove a strategy.

## STOCKEX v3 helpers

These modules expose importable standard-library functions. They do not retrieve data or make recommendations.

- `scripts/market_intelligence.py`: `compound_return`, `price_move_attribution`, `driver_materiality`.
- `scripts/forecasting.py`: `driver_forecast`, `estimate_revision`, `scenario_distribution`, `guidance_score`.
- `scripts/portfolio_execution.py`: `candidate_opportunity_cost`, `execution_estimate`, `position_risk_budget`.
- `scripts/calibration.py`: `validate_transition`, `forecast_error`, `process_score`.

Validate a complete decision packet:

`python3 scripts/decision_packet.py /absolute/path/decision-packet.json`

The command prints a JSON result and exits with status 1 when point-in-time, provenance, mandatory-gate, hard-stop, contradiction, legal-credit, sizing or speculative-control rules fail. Its schema is documented in `schema/decision-packet.schema.json`. Structural validity does not establish that the investment thesis is correct.
