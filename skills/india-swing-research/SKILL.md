---
name: india-swing-research
description: Analyze Indian cash-equity swing setups with dated OHLCV, catalysts, entry conditions, invalidation and execution risks.
---
# India Swing Research

Read ../../references/evidence.md, india-constraints.md, expert-rules.md and news.md. Require valid OHLCV, known adjustment method, latest session date and an objective time window. Use at least sufficient history for each indicator, commonly 250 completed sessions for 200-day context; shorter-history stocks need explicit qualification.

Evaluate benchmark and sector trend, breadth if accessible, relative performance, volatility and drawdown. Separate observed trend from regime forecasts. Typical research setup examples: breakout from an observed base, or pullback within an established trend. Define base/support/resistance from dated price history; avoid hindsight selection. Compute indicators transparently: SMA over specified completed closes; relative return versus benchmark over matching dates; ATR using true range and specified smoothing. Use ATR as volatility context, not a magic stop distance.

Write conditional entry, technical invalidation, realistic target zones, time stop and dated event risks. Show reward/risk after estimated round-trip costs. A default research hurdle of 2:1 planned reward/risk is configurable, not proof of positive expectancy. No quote or no credible stop/target structure means WATCH. Model overnight gaps and circuit locks separately from planned stop loss. Earnings events can invalidate ordinary stop assumptions; do not use an unconfirmed earnings date as fact.

No invented intraday order book or institutional intent. Do not relabel a technical trade as a long term investment after its invalidation. Forward returns require a model and uncertainty, not a chart pattern's asserted success rate. Route sizing to ../india-equity-risk/SKILL.md.
