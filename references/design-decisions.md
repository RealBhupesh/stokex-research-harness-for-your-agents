# Decision-value filter

## Version 5.2 accuracy controls

- Back-adjusted prices for splits, bonuses and consolidations (from the corporate-actions file, or inferred from NSE's adjusted previous close), because raw bhavcopy prices create false breakouts and crashes.
- Raised the bar for PROVEN: a clustered bootstrap lower bound above zero with a Bonferroni correction, plus stability across time folds, because 30 positive trades across many tested setups is often luck.
- Added size-dependent market impact, circuit-locked fills and exits, and gap-loss statistics, so backtests do not assume perfect execution.
- Added a sector map (strength against industry and per-sector caps) and NSE announcements as point-in-time catalysts.
- Added a walk-forward logistic model as a transparent baseline meta-labeler that Jev must beat, with fixed ridge shrinkage rather than a per-run tuned value.
- Added a forward-test journal, because only live, frozen predictions are fully out of sample.

## Version 5.1 Jev meta-labeling

- Added Jev as a meta-labeler on short-term candidates because a calibrated second opinion on each setup instance can raise expectancy without replacing transparent rules.
- Jev sees an anonymized state (no symbols, dates, names or absolute prices) so backtests cannot reward memory of history.
- Jev influences ranking only when a backtest scorecard shows positive Brier skill against setup base rates, AUC above 0.55, at least 50 judged trades and higher filtered expectancy. Otherwise it is information only.

## Version 5.0 short-term setups and market-data signals

- Added short-term and technical setups (`BREAKOUT_52W`, `BASE_BREAKOUT_VCP`, `PULLBACK_UPTREND`, `DELIVERY_ACCUMULATION`, `DEAL_FOLLOW_THROUGH`, `EARNINGS_GAP_DRIFT`, `RS_LEADER_IN_WEAK_TAPE`) and F&O-derived signals (`LONG_BUILDUP`, `SHORT_COVERING`, rollover, ban status). The v2 filter excluded unvalidated technical indicators. That condition is now met: the walk-forward backtester (`python -m stockex.cli backtest`) supplies out-of-sample evidence for each frozen setup definition.
- A setup without a measured edge (fewer than 30 scorecard trades, or non-positive expectancy) is labelled `UNPROVEN` and ranked below proven setups. It is never presented as an edge.
- F&O data is used as a positioning signal only. The harness does not recommend futures or options trades.
- NSE end-of-day files are imported from user or agent-browser downloads (`python -m stockex.cli market-import`). No scraping or automated retrieval is implemented.
- Added `AGGRESSIVE_SHORT_TERM` as a first-class mandate served by [momentum trading](../skills/india-momentum-trading/SKILL.md). The hard risk plan per pick replaces reframing, so an aggressive request gets a disciplined answer rather than a redirect.
- Added the [analyst playbook](analyst-playbook.md), [short-term playbook](short-term-playbook.md), [market calendar](india-market-calendar.md) and [sector KPIs](sector-kpis.md) so that agents apply specific Indian-market checks, sources and invalidation rules instead of generic reasoning.

## Version 3.0 institutional research OS

- Added a fifteen-stage gated workflow because independent components did not guarantee that evidence, forecasts, risk and the final action reconciled.
- Added world-to-stock transmission and benchmark-relative price attribution because finances alone cannot explain changing expectations, discount rates, flows or market structure.
- Preserved unexplained price residuals because temporal proximity between news and price does not prove causality.
- Added point-in-time packet validation, contradiction blocking and independent IC actions because a persuasive narrative or high score must not bypass a failed gate.
- Added driver forecasts, estimate revisions, management calibration and catalyst event trees because valuation must connect to operating assumptions and a recognition path.
- Added legal-credit, relationship, opportunity-cost and execution controls because theoretical upside can be dominated by refinancing, group exposure, alternatives, friction or inability to exit.
- Added frozen thesis transitions and a performance lab because a research process cannot improve if it rewrites predictions after outcomes.
- Kept data retrieval outside deterministic scripts. No authenticated live feed was configured or tested, so the package cannot claim automatic or continuous coverage.

## Version 2.1 risk and research depth

- Added a layered risk detector because a single composite risk score can hide an audit, liquidity, solvency or mandate failure.
- Added hard-stop gates, explicit UNKNOWN likelihood and residual-risk fields to avoid false numerical precision.
- Added backward-looking market-risk and liquidity-exit helpers. They are diagnostics only and carry limitations for gaps, circuits and regime change.
- Added a reusable deep-research prompt that requires primary filings, real chart data, competing narratives, risk detection and an adversarial review before opinion formation.

## Version 2.0 decision-value filter

Included because they change evidence quality or a measurable decision: point-in-time availability, reverse expectations, objective-return plausibility, factor interactions, earnings acceleration with base-effect checks, line-item forensic gates, exit/trap gates, portfolio exposure/covariance context, frozen predictions, walk-forward evaluation and calibration metrics.

Included only as contextual overlays: market regime observations, FPI/DII activity and catalyst freshness. They can alter scenarios, timing or limits, but they do not receive an automatic predictive score until validated.

Not implemented as decision scores:

- arbitrary catalyst half-life constants across all event types;
- headline sentiment or number of positive articles;
- opaque forensic or “manipulation probability” composites;
- famous-investor endorsement scores;
- automatic self-modification from recent winners and losers;
- regime probabilities without a frozen model and calibration;
- technical indicators that duplicate existing momentum information;
- an automated recommendation or monitoring claim without a configured data feed.

The harness may add these later only when there is point-in-time data, a precise definition, a causal or predictive hypothesis, out-of-sample evidence, and a clear rule for how the result changes an action. Complexity alone is not an improvement.
