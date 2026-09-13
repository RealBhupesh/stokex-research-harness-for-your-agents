# Return plausibility before stock search

When a user specifies a target return, compute the required holding-period return and equivalent compounded annual rate before screening. Keep desired return separate from expected return.

## Classification

Classify the objective, not the user:

- ordinary mandate: target broadly compatible with the selected asset and horizon;
- aggressive: requires above-normal outcomes and material downside tolerance;
- speculation: outcome depends on unusually strong repricing, catalyst or volatility;
- extreme speculation: target implies a multiple over weeks/months, leverage, or a tail outcome.

Do not use fixed universal cutoffs as empirical truth. Support the classification with benchmark history, observed volatility, drawdowns and scenario mechanics from dated data. A high target does not increase a candidate's expected return.

## Probability discipline

If a probability is requested, name the model and inputs. The included GBM estimate is only a lognormal sensitivity using assumed annual drift and volatility. It ignores jumps, circuits, liquidity, parameter uncertainty and changing regimes. Report probabilities across a range of plausible inputs, never a single precise number as fact. Historical hit rates require point-in-time backtesting.

Output required return, annualized equivalent, scenario losses, assumptions, classification, and whether the mandate should be reframed. The harness may still research speculative candidates, but the final decision must not describe the desired outcome as likely without evidence.
