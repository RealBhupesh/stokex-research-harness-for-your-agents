# Decision-value filter for v2 additions

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
