# Transparent ranking heuristics
Scores order research effort, not probabilities of profit. Weights below are initial configurable choices and have not been backtested. Preserve the selected weights before looking at winners.

| Component | Long term weight | Swing weight |
|---|---:|---:|
| Business/financial quality | 25 | 10 |
| Governance/evidence strength | 20 | 15 |
| Valuation/downside | 25 | 10 |
| Growth or dated catalyst | 15 | 20 |
| Price structure/relative strength | 5 | 25 |
| Liquidity/execution and risk fit | 10 | 20 |

Grade each 0 to 5 with evidence and counterevidence: 0 adverse, 1 weak, 2 below acceptable, 3 acceptable, 4 strong, 5 exceptional relative to relevant peers. Total = sum(weight * grade / 5). Missing = NA, not zero and not neutral. Publish evidence coverage as sum of weights with supported grades / 100. Rank only comparable candidates with at least 80% supported coverage; below that remains SCREEN ONLY. Never renormalize away a missing governance or valuation category. Eligibility gates can reject an otherwise high score.

Tie handling: prefer stronger evidence and lower downside/concentration risk; if distinction remains uncertain, give a tie or wait. Show how ±1 grade on subjective components changes the order. Do not use a numerical cutoff to manufacture confidence.

Default screening hypotheses, customizable and not universal: positive multi-year cumulative CFO for established nonfinancials; sustainable returns above defensible cost of capital; manageable maturity/interest burden under stress; adequate liquidity for proposed ticket. Use sector-specific exemptions with written reasons. Do not apply a fixed ROCE or debt/equity threshold across banks and factories.
