# Multi-layer risk detection

Run this before forming an opinion and again after valuation and technical analysis. The purpose is to identify how the thesis can fail, whether the loss can be survived and whether the evidence is reliable. It is not a fraud score, a prediction of maximum loss or a substitute for judgment.

## Risk record

For every material risk record:

- category and concise risk statement;
- observed fact versus inference;
- primary source ID, document date, period and page/table;
- causal mechanism from trigger to earnings, cash flow, valuation, price or exit;
- horizon and exposure;
- likelihood: HIGH / MEDIUM / LOW / UNKNOWN, only when evidence supports it;
- impact: BLOCKER / HIGH / MEDIUM / LOW;
- detectability and warning indicators;
- mitigants and evidence that they work;
- thesis-break threshold or monitoring trigger;
- residual risk and confidence after mitigants;
- status: OPEN / MONITOR / MITIGATED / RESOLVED.

Do not multiply ordinal labels into a fake expected-loss number. Do not average a BLOCKER away. UNKNOWN is a valid likelihood when evidence cannot support a probability.

## Detection layers

1. **Evidence and identity:** correct issuer, ISIN, security, corporate actions, timestamps, consolidated basis, amended filings, source conflicts and missing current data.
2. **Business and competition:** customer/supplier concentration, cyclicality, disruption, pricing power, capacity utilization, key-person dependence, geographic exposure and unit-economics fragility.
3. **Earnings and accounting:** PAT-to-CFO conversion, working capital, receivables ageing, inventory, capitalized expenses, other income, exceptional items, cash taxes, segment reconciliation and aggressive estimates.
4. **Balance sheet and solvency:** net debt, maturity wall, interest coverage, covenants, refinancing, guarantees, contingent liabilities, off-balance-sheet exposure, credit-rating direction and currency mismatch.
5. **Governance and ownership:** audit qualification/resignation, promoter pledge or selling, related-party transactions, dilution, warrants, preferential allotments, remuneration, regulatory action and capital allocation.
6. **Valuation and expectations:** reverse-DCF requirements, duration, terminal-value dependence, multiple compression, peer mismatch, dilution, cyclically peak earnings and lack of margin of safety.
7. **Market and technical:** realized volatility, beta, drawdown, gap history, trend deterioration, relative strength, volume quality, event clustering and crowded positioning. Technical indicators describe market behavior, not business truth.
8. **Liquidity and exit:** free float, average daily traded value, spread/depth, price bands, circuit history, trade-to-trade, SME status, suspension, ASM/GSM and days-to-exit under normal and stressed participation.
9. **Event, legal and regulatory:** results, court or regulator decisions, licenses, contracts, plant incidents, corporate actions, policy changes, tax exposure and catalyst timing.
10. **Macro and sector:** rates, INR, commodities, oil, weather, government spending, regulation, geopolitics and sector cycles. Link each variable to the issuer rather than listing generic macro risks.
11. **Portfolio:** single-name, sector, factor, promoter-group, lender, geography and common-catalyst concentration; correlations and liquidity under joint stress.
12. **Mandate:** horizon mismatch, required-return implausibility, loss exceeding the user's tolerance, leverage, near-term liabilities and reliance on an unconfirmed catalyst.

## Hard-stop gates

Return BLOCKED or INSUFFICIENT DATA when a controlling issue cannot be resolved or bounded. Examples include:

- issuer/security identity or action-adjusted price cannot be verified;
- latest controlling filing, quote or material announcement is unavailable;
- unresolved audit qualification, resignation or filing inconsistency that can materially change the thesis;
- suspension or market structure makes the assumed exit indefensible;
- position cannot exit within the approved liquidity limit, including a stressed-volume check;
- required return, horizon or potential loss conflicts with the stated mandate;
- valuation depends on an assumption outside a defensible evidence range;
- thesis relies chiefly on rumor, social-media activity, a famous holder or unverified news;
- material legal, regulatory, pledge, dilution or solvency exposure cannot be quantified or bounded.

A hard stop does not always mean the company is bad. It means the requested decision is not underwritable with the current evidence or terms.

## Quantitative diagnostics

Use matched, adjusted return series and state the frequency, window, end date and benchmark. When relevant calculate annualized volatility, beta, maximum drawdown, downside deviation, historical VaR/CVaR and worst period. Use `scripts/decision_helpers.py market_risk_metrics` for transparent arithmetic. These measures are backward-looking, window-sensitive and can fail during gaps, circuits, illiquidity or regime change.

Estimate exit sessions using position value, average daily traded value and an explicitly approved maximum participation rate. Use `liquidity_exit_days`, then stress lower traded value and wider spreads. Never treat the estimate as an execution guarantee.

Stress at least three coherent scenarios rather than moving one variable at a time:

- company-specific failure, such as margin, working-capital or refinancing shock;
- sector/macro shock, linked to the issuer's actual exposures;
- market/liquidity shock with multiple compression, gap and lower traded value.

For long-term ownership, express portfolio loss as position weight multiplied by scenario drawdown, then include correlated holdings. For short-term trades, distinguish planned stop loss, gap loss and locked-circuit loss.

## Final risk posture

- **ACCEPTABLE:** no blocker; material risks are evidenced, bounded and compatible with the mandate.
- **ELEVATED:** no blocker; one or more high risks require smaller exposure, a better entry or a specific trigger.
- **HIGH:** downside, uncertainty or exit risk dominates under current terms. Normally WATCH or REJECT.
- **UNUNDERWRITABLE:** controlling evidence is missing or a hard-stop gate fails. BLOCKED or INSUFFICIENT DATA.

State the three risks most likely to make the opinion wrong, the three largest-loss pathways, early-warning indicators and the exact evidence that would change the posture. Risk posture constrains the decision but never creates a buy signal.
