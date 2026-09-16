# Requests to reuse
“Run the complete STOCKEX v3 workflow on [company]. Do not form an opinion until the evidence room, world-to-stock map, price-move attribution, normalized history, driver forecasts, scenarios, risk register and independent IC review are complete.”

“Why has [stock] risen/fallen over [exact period]? Adjust for corporate actions, compare Nifty, sector and peers, inspect volume and event timing, test competing explanations and preserve anything unexplained.”

“Find Indian stocks that could produce [extreme return] over [short horizon]. Treat it as asymmetric speculation, not a promised base case. Require a dated catalyst, executable liquidity, capped capital at risk, total-loss acceptance and pre-event and post-event exit plans.”

“Use the Indian stock research workflow. I have ₹[capital], my goal is [goal], my horizon is [time], and I can tolerate [loss in rupees or percent]. Screen [universe], exclude [sectors], compare the top candidates and tell me whether to act or wait. Use fresh NSE/BSE disclosures and timestamped prices.”

“Research [company and ticker] for 3 to 5 year ownership. Compare three relevant peers, normalize cash flows, build bear/base/bull valuations, show what the price implies, and give thesis kill conditions.”

“Use `prompts/deep-stock-research.md` to investigate [company and ticker]. Do not form an opinion until you have read the annual-report notes, subsequent exchange filings, mapped competing market perceptions, produced charts from actual data, completed the risk register and performed the skeptical review.”

“Find a cash-equity swing setup for 2 to 8 weeks. No leverage. My total trading capital is ₹[amount], total concurrent risk budget is [amount], per-trade planned risk is [amount], and sector exposure is [limit]. Show the entry trigger, stop logic, realistic reward after costs, event risk and reasons to wait.”

“Review my previous thesis using the monitoring template. What changed in the evidence, valuation and risks? Do not change the original thesis silently.”

“Update thesis [ID] using new evidence. Classify each trigger, identify affected assumptions, rerun only the necessary stages, validate the state transition and preserve the frozen original record.”

“Analyze [company]. Calculate only the applicable Piotroski, Altman, Beneish, CAGR, cash-return and valuation diagnostics, showing every component and limitation. Verify whether any notable investors, funds, promoters or insiders hold or recently traded the stock using dated primary disclosures. Map material news from the last [period], deduplicate repeated headlines, and explain what could affect earnings or valuation.”

“I want ₹[capital] to become ₹[target] in [days/months]. Run return plausibility before searching. Separate desired return from estimated probability, show loss scenarios, classify the mandate, and do not force a stock.”

“Evaluate [stock] as an addition to this portfolio: [holdings and weights]. Show duplicate sector, factor and catalyst exposure, before/after stress loss, and whether an index alternative is more sensible.”

“Run the multi-layer risk detector on [stock]. Show hard stops, accounting and governance flags, solvency, valuation expectations, event risk, volatility, drawdown, historical VaR/CVaR, normal and stressed days-to-exit, portfolio concentration and the evidence that would change the risk posture.”

“Test model version [version] using this point-in-time dataset. Reject future information and current-survivor universes, use walk-forward windows and realistic costs, preserve an untouched holdout, then complete the backtest and calibration reports.”

## Local point-in-time store

The first executable release is an offline local SQLite evidence store. It
works only with evidence you supply. It does not scrape exchanges and cannot
guarantee source authenticity or dataset completeness. The basic workflow is:

```bash
python -m stockex.cli init research.sqlite3
python -m stockex.cli ingest research.sqlite3 evidence.jsonl
python -m stockex.cli packet research.sqlite3 INE000A01001 --cutoff 2026-06-01T10:00:00+05:30
python -m stockex.cli integrity research.sqlite3
```

Use a stable security ID or ISIN and a timezone-aware cutoff. A passing
integrity result confirms internal consistency only. It does not establish
authenticity, completeness, suitability or predictive power.

## Optional local discovery
Copy the full `indian-stock-research` folder to your assistant's supported skill directory, commonly `~/.codex/skills/`. Keep all references and subfolders together. For another platform, use its documented skill import mechanism or load `SKILL.md` manually. This archive is portable, not automatically installed in every chat. The specialist folders can be read by the orchestrator without installing them separately.

## Before the first actual stock run
Supply horizon, objective, tolerable loss, investable capital and current holdings if sizing is wanted. A broker read-only export or dated CSV is enough for many price checks. Do not provide passwords or session tokens in chat. Free public sources support research, but do not guarantee a complete, timely market-wide screen.

For a full run, use `prompts/deep-stock-research.md`. Validate a completed JSON decision packet with `python3 scripts/decision_packet.py packet.json`. The scripts operate only on supplied inputs and do not provide a market-data feed.
