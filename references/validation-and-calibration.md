# Walk-forward validation and forecast calibration

Backtesting tests a fully specified rule. It does not validate discretionary hindsight explanations.

## Minimum backtest contract

- Freeze universe, eligibility, features, weights, decision date, holding/exit rule and benchmark before evaluating the test period.
- Use point-in-time data, historical constituents, original/revised filing vintages, corporate actions, delistings and failures.
- Apply executable timing: a filing after close cannot receive the prior close. Model slippage, all relevant charges, taxes where the analysis requires after-tax results, circuits, liquidity caps and unfilled orders.
- Use chronological train/validation/test or walk-forward windows. Keep a final untouched holdout. Parameter selection on the test set invalidates the test.
- Compare against simple alternatives such as the relevant TRI and equal-weight/sector controls.
- Report CAGR, excess return, volatility, Sharpe/Sortino with stated risk-free convention, maximum drawdown, tail loss, turnover, hit rate, payoff ratio, exposure, sample count and confidence intervals where defensible.
- Run sensitivity across nearby parameters, subperiods, sectors and market regimes. A result that vanishes after small changes is fragile.

LLMs can remember historical outcomes, so historical narrative evaluation must be constrained to a dated evidence packet. Do not call the included metric calculator a backtest engine; it only scores supplied realized returns.

## Prediction journal

Before the outcome, freeze prediction ID, decision timestamp, evidence packet hash or source ledger, horizon, benchmark, expected range, scenario probabilities, thesis, catalyst, invalidation and decision. Do not edit the original record after outcome observation; append a review.

For mutually exclusive outcomes, probabilities must be in `[0,1]` and sum to 1. Evaluate Brier score and log loss, reliability bins, coverage of predicted ranges and benchmark-relative outcomes. Small samples do not support confident calibration claims. Segment results by horizon and decision type rather than mixing 5-year investments with 2-week trades.

Learning rule: update weights only after a documented, sufficiently large out-of-sample evaluation. Keep the old model version and record why the new version was accepted. Do not let one lucky winner teach the harness that its narrative was correct.
