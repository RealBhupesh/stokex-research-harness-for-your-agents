# Portfolio-aware decision layer

When holdings are supplied, evaluate the candidate as an incremental portfolio decision, not a standalone winner.

## Required views

1. Direct weights by issuer, sector, market cap, promoter group and security type.
2. Common economic exposures such as defence procurement, oil, INR, rates, government capex, rural demand, commodity cycle, export geography and one regulatory decision.
3. Return correlation from a stated historical window, plus stress scenarios. Correlation is unstable and can rise during crises.
4. Liquidity and exit concentration relative to the user's ticket.
5. Portfolio stress loss and contribution, including existing positions and the candidate.

Five defence stocks are not five independent bets. Map each holding to one or more factor/exposure buckets with evidence and show the effective weight under a named stress. Do not infer diversification from ticker count.

For optimization, constraints and expected returns dominate the mathematical solution. Never present a mean-variance weight as personally suitable without transparent assumptions and user-approved limits. If holdings are unknown, state that portfolio-aware sizing is unavailable and provide formulas only.
