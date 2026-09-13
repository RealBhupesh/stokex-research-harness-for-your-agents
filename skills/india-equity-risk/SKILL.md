---
name: india-equity-risk
description: Translate Indian equity research into loss-aware sizing and monitoring while accounting for portfolio concentration and illiquid exits.
---
# India Equity Risk

Read ../../references/intake.md, return-plausibility.md, india-constraints.md, portfolio-context.md and risk-detection.md. Resolve risk scope explicitly: total capital, allocated capital, planned trade loss, stress loss and tolerable portfolio drawdown are different. Do not infer sizing from a generic “moderate risk” label.

Build ../../templates/risk-register.md before the final opinion. Check every risk layer, document the causal mechanism and preserve UNKNOWN when likelihood cannot be supported. Hard-stop gates override scores, famous-holder signals, price momentum and apparent upside. Return ACCEPTABLE, ELEVATED, HIGH or UNUNDERWRITABLE risk posture with the three most likely thesis failures and largest-loss pathways.

For cash-equity trading, planned size = minimum of floor(rupee risk budget / (entry-stop+per-share friction)), floor(position cash cap / entry), and liquidity cap. Reserve cash for fees and account-level limits. The helper accepts a cash cap already reduced for fixed charges. A stop can fail; show stress size based on a gap scenario separately. User tolerable loss does not mean it is guaranteed.

For long term ownership, use bear/stress loss and portfolio exposure limits, not an arbitrary tight technical stop. If stress loss fraction is d and portfolio rupee stress budget is B, candidate exposure cannot exceed B/d before other concentration/liquidity limits. Correlated holdings need a joint scenario, not addition of independent probabilities.

Configurable cautious starting policy for discussion: no leverage, planned trade risk 0.25% to 0.5% of trading capital, no new position beyond a user-approved aggregate risk budget; illustrative single-name cap 5% of an overall diversified portfolio. These are design defaults, not personalized advice or validated optimal values. If capital/holdings and approved limits are missing, present formulas only.

When matched adjusted return series exist, use `../../scripts/decision_helpers.py market_risk_metrics` and disclose window, frequency, end date and benchmark. Use `liquidity_exit_days` with normal and stressed traded value. Historical volatility, beta, drawdown and VaR/CVaR are descriptive, not maximum-loss forecasts. A planned stop can fail during gaps, circuits and illiquidity.

Define entry, add, trim, exit, time stop, thesis breach and monitoring frequency. Averaging down requires fresh thesis review and remaining risk capacity, never an automatic response to losses. Research authorization does not authorize order placement. Produce a risk section, not a guaranteed maximum-loss claim.
