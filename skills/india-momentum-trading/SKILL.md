---
name: india-momentum-trading
description: Produce aggressive 1–10 trading day NSE/BSE cash-equity picks from verified catalysts, price-volume-delivery structure and F&O positioning signals, each with a hard risk plan (entry trigger, stop, targets, time stop, size) and the setup's measured track record.
---
# India Momentum Trading

Use this skill for the `AGGRESSIVE_SHORT_TERM` mandate ([intake](../../references/intake.md)): ranked long picks in cash equities, held for 1–10 trading days. The mandate is served directly. Don't push the user to reframe it; the discipline comes from the risk plan. Read the [short-term playbook](../../references/short-term-playbook.md), [market calendar](../../references/india-market-calendar.md), [sector KPIs](../../references/sector-kpis.md), [India constraints](../../references/india-constraints.md) and [news](../../references/news.md). The output supports research; it places no orders. F&O data is used as a positioning signal only, and this skill never recommends futures or options trades.

## Workflow

### 1. Freeze the mandate

Record:

- as-of timestamp (IST) and the last completed session date;
- trading capital;
- risk per trade (default 1%, configurable 0.5–2%);
- maximum concurrent positions (default 5);
- maximum holding period (≤ 10 sessions);
- minimum R:R after costs (default 2.0);
- daily and weekly loss limits;
- a minimum traded-value floor;
- exclusions.

Capital, risk per trade and max positions are required for sizing. If any is missing, produce unsized ideas labelled `UNSIZED` and ask once.

### 2. Check the regime

Compute the regime inputs from dated data: Nifty against its 50/200 DMA and their slopes, % of Nifty 500 above the 50 DMA, advance/decline, new highs against new lows, India VIX level and trend, and the FII cash-flow streak. Then apply the regime table in the [short-term playbook](../../references/short-term-playbook.md#market-regime-when-to-be-aggressive-and-when-to-sit-out). The regime scales risk per trade and the position count. The scanner prints `RISK_ON`, `NEUTRAL` or `RISK_OFF` with its inputs (read them as Aggressive, Normal and Defensive); in `RISK_OFF` it already halves the risk budget and keeps only relative-strength leaders. Sit out is your call from the extra inputs the scanner does not compute. In Sit out the correct output is no new picks.

### 3. Generate candidates

When a STOCKEX database with imported NSE market files exists:

```text
python -m stockex.cli market-status DATABASE
python -m stockex.cli scan DATABASE --as-of YYYY-MM-DD --capital N --risk-per-trade 0.01 --format md
```

- Load the data first with `python -m stockex.cli market-import DATABASE FILES...`, using the NSE end-of-day files listed in [tools](../../references/tools.md).
- Check `market-status` for coverage gaps (missing sessions, no F&O file, no delivery data) before you trust a scan.
- Optionally attach measured evidence with `--scorecard scorecard.json`, produced by:

```text
python -m stockex.cli backtest DATABASE --from D1 --to D2 --out scorecard.json
```

The backtest window must end before the scan's `--as-of` date.

To use Jev as a trade filter, add `--jev` to both the backtest and the scan (needs `TYPESAFE_API_KEY`). The backtest measures whether Jev's follow-through probabilities beat each setup's base rate ([Jev meta-labeling](../../references/jev-meta-labeling.md)). Jev filters and re-ranks picks only when the scorecard marks it `PROVEN`; otherwise its column is information only.

Without a database, do the manual equivalent from dated NSE bhavcopy, delivery, F&O, deal and index files. Apply the same setup definitions (`BREAKOUT_52W`, `BASE_BREAKOUT_VCP`, `PULLBACK_UPTREND`, `LONG_BUILDUP`, `SHORT_COVERING`, `DELIVERY_ACCUMULATION`, `DEAL_FOLLOW_THROUGH`, `EARNINGS_GAP_DRIFT`, `RS_LEADER_IN_WEAK_TAPE`) and state which files and dates you used. Never invent a quote, OI figure or delivery %.

### 4. Verify the catalyst and the calendar

For each candidate, find the primary source for any catalyst: NSE/BSE announcement with broadcast time, results PDF, con-call, bulk/block deal file, PIT/SAST filing, index-provider release or government notification. Classify it NEW, ACTIVE, PRICED or STALE ([news](../../references/news.md)). Then build the next-10-sessions calendar ([market calendar](../../references/india-market-calendar.md#how-to-build-the-next-10-sessions-event-calendar)). An unplanned binary event (results, court, regulator) inside the holding window means you reduce size, make it an explicit event trade, or reject the candidate.

### 5. Confirm with signals

Require confirmation that fits the setup:

- RVOL and delivery ratio against the stock's own history;
- a close location in the range;
- RS against Nifty and the sector index;
- sector breadth;
- for F&O stocks, the price×OI quadrant (long buildup beats short covering for anything longer than 2–3 days), rollover and IV context.

Conflicting signals lower the rank. A short-buildup or long-unwinding reading on a long candidate rejects it unless a catalyst clearly outweighs it, and you must say so.

### 6. Build the hard risk plan

Every pick needs:

- an entry trigger (a level plus a condition, such as "close above ₹X" or "buy-stop ₹X");
- a structure-based stop bounded by ATR;
- T1 (about 1.5R) and T2 (about 3R or the next resistance);
- R:R to T2 after estimated round-trip costs and slippage, at or above the mandate minimum;
- a time stop;
- quantity = (capital × risk per trade × regime multiplier) / (entry − stop), capped by liquidity (scanner default ≤ 2% of the 20-day median traded value) and the position-value cap (default 20% of capital);
- a gap and circuit stress loss.

Block, and list with the reason:

- ASM/GSM names, trade-for-trade (T2T) series and the F&O ban list;
- SME names unless opted in;
- names below the traded-value floor;
- names with frequent circuits;
- names whose planned R:R fails.

Respect the max positions, the sector concentration limit (≤ 2 per sector) and the total open-risk cap.

### 7. Output

Fill [trade ideas](../../templates/trade-ideas.md).

- **Ranking:** measured setup edge first, then catalyst strength and freshness, then confirmation quality, then liquidity. Ranking is not decided by the size of the expected return.
- **UNPROVEN setups:** a setup that the scorecard marks `UNPROVEN` (fewer than 30 trades or non-positive expectancy), or one with no scorecard, must be labelled `UNPROVEN` in the track-record column and ranked below every proven setup.
- **Jev:** report Jev's probability to T1, catalyst quality and crowding flag with the status (`PROVEN`, `UNPROVEN` or `NO_SCORECARD`). Never present an unproven Jev probability as a reason to take a trade.
- **No picks:** if nothing qualifies, say so plainly: "No candidate meets the mandate today." Then list the closest rejects and what would change them.
- **Journal:** log every pick for post-trade review, so the scorecard and the [validation](../../references/validation-and-calibration.md) loop can learn from it.

## Hard rules

- No averaging down, no widening stops, and no converting a failed trade into an investment. Route that to a new, separate long-term analysis if the user asks.
- A catalyst without a primary source is a rumour and cannot justify a rank.
- Show the return math ([return plausibility](../../references/return-plausibility.md)) but proceed under the risk plan.
- Sizing and portfolio risk go to the [risk skill](../india-equity-risk/SKILL.md) when the user's holdings are known.
