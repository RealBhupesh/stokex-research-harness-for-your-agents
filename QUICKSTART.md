# Requests to reuse
“Use the Indian stock research workflow. I have ₹[capital], my goal is [goal], my horizon is [time], and I can tolerate [loss in rupees or percent]. Screen [universe], exclude [sectors], compare the top candidates and tell me whether to act or wait. Use fresh NSE/BSE disclosures and timestamped prices.”

“Research [company and ticker] for 3 to 5 year ownership. Compare three relevant peers, normalize cash flows, build bear/base/bull valuations, show what the price implies, and give thesis kill conditions.”

“Use `prompts/deep-stock-research.md` to investigate [company and ticker]. Do not form an opinion until you have read the annual-report notes, subsequent exchange filings, mapped competing market perceptions, produced charts from actual data, completed the risk register and performed the skeptical review.”

“Find a cash-equity swing setup for 2 to 8 weeks. No leverage. My total trading capital is ₹[amount], total concurrent risk budget is [amount], per-trade planned risk is [amount], and sector exposure is [limit]. Show the entry trigger, stop logic, realistic reward after costs, event risk and reasons to wait.”

“Review my previous thesis using the monitoring template. What changed in the evidence, valuation and risks? Do not change the original thesis silently.”

“Analyze [company]. Calculate only the applicable Piotroski, Altman, Beneish, CAGR, cash-return and valuation diagnostics, showing every component and limitation. Verify whether any notable investors, funds, promoters or insiders hold or recently traded the stock using dated primary disclosures. Map material news from the last [period], deduplicate repeated headlines, and explain what could affect earnings or valuation.”

“I want ₹[capital] to become ₹[target] in [days/months]. Run return plausibility before searching. Separate desired return from estimated probability, show loss scenarios, classify the mandate, and do not force a stock.”

“Evaluate [stock] as an addition to this portfolio: [holdings and weights]. Show duplicate sector, factor and catalyst exposure, before/after stress loss, and whether an index alternative is more sensible.”

“Run the multi-layer risk detector on [stock]. Show hard stops, accounting and governance flags, solvency, valuation expectations, event risk, volatility, drawdown, historical VaR/CVaR, normal and stressed days-to-exit, portfolio concentration and the evidence that would change the risk posture.”

“Test model version [version] using this point-in-time dataset. Reject future information and current-survivor universes, use walk-forward windows and realistic costs, preserve an untouched holdout, then complete the backtest and calibration reports.”

## Optional local discovery
Copy the full `indian-stock-research` folder to your assistant's supported skill directory, commonly `~/.codex/skills/`. Keep all references and subfolders together. For another platform, use its documented skill import mechanism or load `SKILL.md` manually. This archive is portable, not automatically installed in every chat. The specialist folders can be read by the orchestrator without installing them separately.

## Before the first actual stock run
Supply horizon, objective, tolerable loss, investable capital and current holdings if sizing is wanted. A broker read-only export or dated CSV is enough for many price checks. Do not provide passwords or session tokens in chat. Free public sources support research, but do not guarantee a complete, timely market-wide screen.
