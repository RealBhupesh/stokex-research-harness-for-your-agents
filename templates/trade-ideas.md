# Short-term trade ideas

Research output for the `AGGRESSIVE_SHORT_TERM` mandate ([momentum trading](../skills/india-momentum-trading/SKILL.md)). This is not an order or a guarantee.

## Header

| Field | Value |
|---|---|
| As of (IST) | YYYY-MM-DD HH:MM IST; last completed session YYYY-MM-DD |
| Data coverage | Files and dates used (bhavcopy/delivery, F&O, index, deals, ASM/GSM, ban list); missing sessions or sources |
| Scan command | e.g. `python -m stockex.cli scan DATABASE --as-of … --capital … --risk-per-trade … --format md`, or "manual" |
| Scorecard | File, backtest window (from/to), which must end before as-of; or "none" |
| Regime | Scanner label `RISK_ON` / `NEUTRAL` / `RISK_OFF` (read as Aggressive / Normal / Defensive); SIT OUT is a manual call |
| Regime inputs | Nifty vs 50/200 DMA (values, slopes); % Nifty 500 above 50 DMA; A/D (5–10d); new highs vs lows; India VIX level and 5d change; FII cash streak |
| Mandate | AGGRESSIVE_SHORT_TERM; holding window ≤ N sessions; minimum R:R after costs; exclusions |
| Capital | ₹ |
| Risk per trade | % and ₹ (after regime multiplier) |
| Max concurrent positions / sector cap / open-risk cap | |
| Daily and weekly loss limits | |

## Ranked picks

| Rank | Symbol | Setup | Catalyst (source + date) | Key signals | Entry trigger | Stop | T1 | T2 | R:R after costs | Time stop | Qty / capital | Setup track record | Invalidation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | e.g. `BREAKOUT_52W` | e.g. Q2 results, NSE filing 2026-10-14 18:05 IST; or "technical only" | RVOL, delivery ratio, RS vs Nifty/sector, OI quadrant, close location | e.g. close > ₹ / buy-stop ₹ | ₹ (structure; ATR multiple) | ₹ (~1.5R) | ₹ (~3R or resistance) | x.x | N sessions or date | shares / ₹ and % of capital | trades n, hit rate %, expectancy R; or **UNPROVEN** | Specific price or event that ends the idea |

Proven setups rank above `UNPROVEN` setups. If no row qualifies, write: **No candidate meets the mandate today**, and fill the rejected section.

## Rejected / blocked candidates and why

| Symbol | Scanner / source | Reason (ASM/GSM stage, F&O ban, T2T, illiquid, R:R < minimum, binary event in window, catalyst unverified, conflicting OI, sector cap) | What would change it |
|---|---|---|---|

## Next-10-sessions event risks

| Date (IST) | Event | Affects (symbols / sector / market) | Type (BINARY / SCHEDULED DATA / FLOW) | Source | Plan (hold, reduce, exit before) |
|---|---|---|---|---|---|

Include F&O expiry days, MPC, CPI, FOMC and US CPI (IST), index rebalance dates, results dates for each pick, and record dates. Mark unconfirmed dates as `UNCONFIRMED`.

## Portfolio check

- Open risk after these picks: ₹ / % of capital
- Sector concentration:
- Correlated positions:
- Gap stress (2x stop distance on all positions): ₹

## Post-trade review (fill after exit)

| Symbol | Entry date / price | Exit date / price | Exit reason (stop, T1, T2, trail, time stop, invalidation) | R multiple | Costs ₹ | Rule adherence (yes/no + note) | Catalyst played out? | Lesson / scorecard update |
|---|---|---|---|---|---|---|---|---|

Append the review. Never edit the original pick row after the outcome is known ([post-mortem](post-mortem.md)).
