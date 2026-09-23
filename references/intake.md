# Objective and mandate
Ask only missing questions that affect the decision. Group them in one message, continue independent research while answers are pending.

| Input | Why it changes the work |
|---|---|
| Goal: capital growth, dividend income, trading, capital preservation | Different ranking and exit logic |
| Exact holding window and cash-needed date | Separates trading from ownership and tests equity suitability |
| Capital and amount reserved for essentials | Needed for sizing; never commit essential reserves |
| Maximum tolerable loss, rupees or percent, and its scope | Portfolio drawdown, position stress loss and planned stop loss are different |
| Current holdings and sector exposure | Prevents hidden concentration |
| Experience, monitoring time, cash equity or derivatives | Determines feasible trade expression |
| Exclusions, liquidity needs, market-cap preference | Defines universe |
| Required return and benchmark | Tests whether expectations are realistic |

## Mandate options

Select one: `CAPITAL_PRESERVATION`, `LONG_TERM_COMPOUNDING`, `TACTICAL_SWING`, `EVENT_DRIVEN`, `ASYMMETRIC_SPECULATION` or `AGGRESSIVE_SHORT_TERM`.

`AGGRESSIVE_SHORT_TERM` is for ranked long picks in cash equities held 1–10 trading days, based on catalysts, price-volume-delivery structure and F&O positioning signals. It is a first-class mandate. An aggressive short-term request goes directly to [momentum trading](../skills/india-momentum-trading/SKILL.md) and is not pushed to reframe. Show the [return plausibility](return-plausibility.md) math and proceed under a hard risk plan. Required inputs:

- trading capital;
- risk per trade (default 1%, configurable 0.5–2%);
- maximum concurrent positions.

Optional inputs: maximum holding sessions (≤ 10), minimum R:R after costs (default 2.0), daily and weekly loss limits, and a traded-value floor. Missing required inputs produce `UNSIZED` ideas, not a refusal. The mandate covers cash equities only: F&O data is used as a signal, never as a trade recommendation.

Default research mandate if preferences are absent: Indian listed cash equities, no leverage, broad diversified universe, screen first; no personalized trade size until inputs are known. Do not assume short term means intraday. Ask for exact days/weeks/months if material. Distinguish desired returns from expected returns. If the objective is an essential payment on a fixed near date, explain equity loss risk and allow a no-stock outcome. Do not infer derivatives permission from a request for high returns.

Record as_of_IST, mandate_id, horizon, objective, benchmark, universe, risk_scope, capital_known, exclusions, assumptions and unresolved questions. India Standard Time is UTC+05:30. Weekend research uses the last completed trading session, not an imagined same-day quote.
