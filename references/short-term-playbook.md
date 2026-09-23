# Short-term playbook (1–10 trading days)

This playbook covers NSE/BSE cash-equity setups over a horizon of 1–10 sessions, the confirmation professionals look for, and how to manage risk. All thresholds are configurable starting points. An edge counts only when a walk-forward scorecard measures it ([validation](validation-and-calibration.md)). F&O data is used as a positioning signal only; this harness does not recommend futures or options trades. Use it with the [market calendar](india-market-calendar.md), [sector KPIs](sector-kpis.md), [India constraints](india-constraints.md) and the [momentum trading skill](../skills/india-momentum-trading/SKILL.md).

## Data you need each session

Import these with `python -m stockex.cli market-import`, or read them manually from dated NSE files ([tools](tools.md)):

- full bhavcopy with delivery quantity and delivery % (`sec_bhavdata_full_DDMMYYYY.csv`);
- UDiFF CM and F&O bhavcopies, which give OI, change in OI, settlement price and contracts by expiry;
- the index close file, for Nifty, sector indices and India VIX context;
- bulk and block deals;
- ASM/GSM lists and the F&O ban list;
- FII/DII provisional cash data (NSE, published after the close);
- corporate announcements (NSE/BSE) with broadcast timestamps.

Signals computed from bhavcopy alone:

- **Delivery %** = delivered quantity / traded quantity.
- **Delivery ratio** = today's delivery % / the average delivery % of the previous 20 sessions.
- **Relative volume (RVOL)** = volume / the median volume of the previous 20 sessions (the median resists one-off block prints).
- **ATR(14)**.
- **Distance from the 20/50/200-day SMA**.
- **52-week high proximity.**
- **RS** = the stock's N-day return minus Nifty's (or sector index's) N-day return on the same dates.

Scanner names are the harness's codes. Read each scan's output for the exact parameters the code used, and don't assume the defaults below.

## Scanner map

| Scanner | Setup in this document | Default rule in code (v1, configurable) | Time stop |
|---|---|---|---|
| `BREAKOUT_52W` | 52-week or all-time-high breakout | Close above the prior 252-session high, RVOL ≥ 2, close in the top 40% of the day's range, 60-day RS > 0, delivery ratio ≥ 1 when available; at least 200 sessions of history | 7 |
| `BASE_BREAKOUT_VCP` | Base breakout after volatility contraction (VCP, NR7) | Prior 20-session range ≤ 12% of price, ATR(14)/ATR(50) ≤ 0.8 the day before, close above the 20-session high on RVOL ≥ 1.5, close above the 50 DMA; stop at the 10-session low | 8 |
| `PULLBACK_UPTREND` | Pullback to the 20/50 DMA in an uptrend | 50 DMA above 200 DMA, close above the 50 DMA, 60-day return > 0, a low within 1.5% of the 20 or 50 DMA in the last 5 sessions on below-median volume, then an up day closing above the prior high | 8 |
| `LONG_BUILDUP` | Price up, OI up (F&O stocks) | Stock +2% or more, total futures OI +5% or more, RVOL ≥ 1.5, close above the 20 DMA | 5 |
| `SHORT_COVERING` | Price up, OI down (F&O stocks) | Stock +3% or more, futures OI −5% or more, prior 20-day return ≤ 0 | 3 |
| `DELIVERY_ACCUMULATION` | High delivery in a tight range | 5-session average delivery % ≥ 1.3× its prior 20-session average, 5-session range ≤ 6%, close above the 50 DMA; trigger above the 5-session high | 10 |
| `DEAL_FOLLOW_THROUGH` | Bulk/block deal or QIP/OFS with follow-through | A net bulk/block buy worth ≥ ₹5 crore in the last 3 sessions (same-day sellers excluded), close at or above the deal price | 7 |
| `EARNINGS_GAP_DRIFT` | Results gap that holds, plus post-earnings drift | Yesterday gapped up ≥ 4% on RVOL ≥ 3; today holds above the pre-gap close and yesterday's open. Labelled `UNEXPLAINED_GAP` unless an events file (`--events`) names the catalyst | 10 |
| `RS_LEADER_IN_WEAK_TAPE` | Relative-strength leader while Nifty is weak | Regime `NEUTRAL` or `RISK_OFF`, Nifty 20-day return < 0, 20-day RS ≥ 8% and 60-day RS ≥ 12%, close above the 50 DMA and within 5% of the 50-session high | 10 |

Every scanner hit then goes through the hard risk plan: entry trigger 0.1% above the signal high, structural stop bounded to 1–3× ATR(14), T1 at 1.5R and T2 at 3R, reward/risk to T2 of at least 2 after a 45 bp round-trip cost estimate, and size from capital × risk per trade capped at 20% of capital and 2% of median traded value. BE/BZ series, ASM/GSM/ESM/F&O-ban names, stocks under ₹20, names with median traded value under ₹5 crore and circuit-locked signal days are rejected.

A scanner hit is a candidate, not a pick. Each hit still needs catalyst verification, an event-calendar check, confirmation and a risk plan.

## Catalyst setups

### Quarterly results (`EARNINGS_GAP_DRIFT`)

- **Detect:**
  - Board-meeting intimations on NSE/BSE, usually a few working days before the meeting; the minimum notice is set by LODR, so verify it.
  - Results are filed during or after market hours. Note the broadcast timestamp.
- **Verify:**
  - The filed results PDF: consolidated versus standalone, exceptional items, tax rate, other income.
  - Compare against expectations: consensus if licensed, or the company's own guidance, the prior quarter's run rate and peer prints.
  - A **margin surprise** (EBITDA margin against expectation and against last year) and a **guidance change** (con-call transcript or audio) move stocks more than a revenue beat.
  - Con-call tone: are demand commentary, order pipeline and pricing better or worse than last call?
- **Gap-and-go (long):**
  - The gap holds above the prior day's high through the first hour and the close is in the upper third of the day's range.
  - RVOL ≥ ~2–3x and delivery ratio ≥ ~1.5x.
  - The beat is driven by quality items (volume, margin, guidance) rather than other income or tax.
  - In F&O stocks, confirm with long buildup (OI up with price) rather than short covering alone.
- **Gap-fade (avoid, or exit):**
  - The gap fills below the prior close on day 1–2, or the close is in the lower third on high volume.
  - The beat came from one-offs, or guidance was cut despite a beat.
  - A pre-results run-up of more than ~2–3 ATR in the prior 5–10 sessions already priced the beat.
- **Post-earnings drift:**
  - Stocks with a genuine beat and upward guidance can keep moving for days while estimates are revised.
  - Look for a second entry on a tight 2–4 day consolidation above the gap-day low.
- **Pre-results run-up:**
  - Buying ahead of results on strong monthly data or peer prints is a separate, event-risk trade. Size it for a gap against you.
- **Entry:**
  - Day-1 close or day-2 break of the day-1 high if the gap holds.
  - Or a drift entry on a consolidation breakout.
- **Invalidation:** a close below the gap-day low, or the gap fills.
- **Hold:** 2–10 sessions.
- **Failure modes:**
  - The "sell the news" fade in crowded names.
  - Market-wide risk-off overriding stock news.
  - Misread consolidated numbers.
  - Results released after the close, so the next day's open is the first executable price.

### Order wins

- **Detect:** Reg 30 order disclosures, ministry/PSU tender results, defence ministry (MoD) press releases, railway and NHAI award news.
- **Verify:**
  - Order value against trailing-12-month revenue and the current order book. Material means roughly ≥ 5–10% of TTM revenue, or it changes the order-book/revenue ratio noticeably.
  - Execution period (a ₹1,000 cr order over 5 years ≠ over 1 year).
  - Customer, margin profile, and whether it is L1 (lowest bidder; award not final), LoA/LoI, or a signed contract.
  - Whether it is a repeat of a previously announced L1.
- **Confirm:** RVOL ≥ 2x; the close holds above the pre-news high; delivery ratio up.
- **Failure:**
  - Stocks that announce orders frequently get no reaction.
  - L1 not converted.
  - The order is low-margin EPC.
  - A small cap issues "order" press releases with vague counterparties. Treat these as a red flag.
- **Invalidation:** the close returns below the pre-announcement level.
- **Hold:** 1–5 sessions.

### Bulk and block deals, QIP and OFS (`DEAL_FOLLOW_THROUGH`)

- **Detect:**
  - The NSE/BSE bulk-deal file (a trade of more than 0.5% of equity in a day) and the block-deal file (separate trading window with a minimum size; SEBI revised block-deal rules in 2025, so verify the current size and windows).
  - QIP launch and closure notices with the floor price.
  - OFS notices, which carry separate non-retail and retail days and a floor price.
- **Verify:**
  - Name the buyer and seller (the legal entity, per [ownership](ownership.md)).
  - Is it a promoter selling, a PE exit, a long-only fund buying, or an arbitrage/prop desk? A trading-member or prop buyer that sells the same day is noise.
  - Compare price with the prior close. A QIP at a discount to the floor or a large OFS discount creates an overhang until the stock is absorbed.
- **Confirm:**
  - The price holds above the deal or QIP price for 2–3 sessions with rising delivery.
  - A known long-only buyer takes a new ≥ 1% position.
  - QIP allotment is followed by the stock holding above the issue price.
- **Failure:**
  - A PE seller with remaining stake, which means more supply.
  - The stock breaks below the QIP/OFS price; that level often becomes resistance.
  - Anchor or lock-in expiry dates for recent IPOs. Check the RHP for lock-in schedules.
- **Invalidation:** a close below the deal price.
- **Hold:** 3–10 sessions.

### Promoter open-market buys and pledge releases

- **Detect:** PIT Reg 7(2) disclosures, SAST Reg 29 filings, SAST Reg 31 encumbrance releases, and the SHP encumbrance change.
- **Verify:**
  - The transaction type is an open-market purchase, not ESOP, inter-se, preferential or warrant conversion.
  - Size against promoter holding and ADV.
  - Whether buying is repeated over several days or filings.
  - A pledge release funded by selling shares elsewhere is neutral.
- **Confirm:** repeated filings, price holding a higher low, delivery ratio > 1.5x.
- **Failure:**
  - Token buys.
  - Buys during a falling stock that is being defended against margin calls.
  - Trading-window restrictions (closure from quarter end until results) that mean the next buy cannot come soon.
- **Invalidation:** a new low below the level where the promoter bought.

### Buyback, bonus, split, dividend and record dates

- **Detect:** board-meeting intimations and outcomes, and record-date notices on NSE/BSE.
- **Verify:**
  - Buyback route (tender versus open market), price premium to market, and size as a % of free float.
  - Acceptance-ratio estimate for tender buybacks. Taxation of buybacks changed in 2024, so verify the current treatment; it changes the economics of tendering.
  - Bonus and split change liquidity, not value.
- **Short-term pattern to test:** a run-up into the record date and weakness on the ex-date. Remember T+1 settlement: to be on record you must buy at least one trading day before the record date, so verify for holidays.
- **Failure:** buyback price close to market; small size relative to float.

### Index inclusion and exclusion

- **Detect:**
  - NSE Indices semi-annual rebalance press releases. Nifty 50 and Next 50 changes are usually announced about four weeks before an effective date near the end of March and September; verify on niftyindices.com.
  - BSE/Asia Index Sensex reviews (semi-annual).
  - MSCI quarterly index reviews: announcements in February, May, August and November, effective at the close of the last business day of the month; verify the dates on msci.com.
  - FTSE quarterly reviews.
  - Sell-side "likely inclusion" lists are leads only.
- **Estimate passive flow:**
  - Flow ≈ passive AUM tracking the index × new index weight. Weight is set by free-float market cap and any capping, so use the methodology document.
  - Divide by the 20-day ADV in value to get days of volume.
  - A flow above about 1–3 days of ADV is meaningful. More than 5 days is large.
  - Treat passive AUM as an estimate and cite its source.
- **Pattern:**
  - Pre-announcement anticipation, then the announcement jump.
  - Drift into the effective date.
  - Heavy volume at the closing auction on the effective day, with frequent reversal afterwards.
  - Exclusions show the mirror image.
- **Failure:** widely anticipated inclusions are front-run; the effective-day close is often the local extreme.
- **Invalidation:** a close below the announcement-day low.
- **Hold:** announcement to effective date, and exit into or before the effective-day close.

### F&O segment inclusion and exclusion

- **Detect:**
  - NSE circulars adding stocks to derivatives, with eligibility criteria SEBI revises periodically (MQSOS, MWPL, average daily delivery value; verify the current criteria).
  - Exclusion circulars: no new contracts after existing expiries.
- **Pattern:** inclusion can bring liquidity and arbitrage demand. Exclusion ends futures-based shorting and hedging. Treat both as event trades with sizes you can measure.

### Policy events

- **Covers:** the Union Budget, PLI approvals and disbursals, customs duty changes, anti-dumping and safeguard duties, US and other tariffs, PSU disinvestment/OFS, defence procurement (DAC approvals, then contracts), railway budgets, fertiliser subsidy and ethanol pricing.
- **Detect:** official releases (PIB, ministry notifications, CBIC and DGTR notifications, gazette).
- **Verify:** the notification text, effective date and covered HS codes/products. A headline is not a notification.
- **Confirm:** the sector index moves with breadth (most constituents up), and the leading stocks close near their highs.
- **Failure:**
  - "Buy the rumour, sell the Budget."
  - DAC approval (acceptance of necessity) mistaken for an order.
  - Disinvestment OFS priced at a discount, which caps upside near-term.

### Monthly data releases

- **Covers:** auto sales (1st), GST collections, PMIs, CPI/IIP, core sector, AMFI flows, RBI sectoral credit, cement proxies, power demand, air traffic (DGCA), port cargo.
- **Look at:** the stock-level surprise against expectation and trend (YoY, adjusting for festival timing and base effects), not the absolute number.
- **Confirm:** peer-relative move on the day.
- **Failure:** festival-shift distortion, since Diwali in October versus November swings YoY; dispatch (wholesale) versus retail (FADA/Vahan) divergence, which signals inventory build.

### Commodities and currency

- **Map:**
  - Crude up hurts OMCs, paints, tyres, aviation and chemicals, and helps upstream.
  - Metals up helps producers and hurts user industries.
  - A weak INR helps IT, pharma exporters and textiles, and hurts importers and unhedged foreign-currency borrowers.
- Use the [world-to-stock transmission](world-to-stock-transmission.md) map.
- **Verify:** the price series with date, and the company's hedging policy (AR).
- **Failure:** lagged pass-through, inventory gains or losses, contract pricing with a quarter's delay.

### Global cues

- **GIFT Nifty** (NSE IX) trades before the Indian open and indicates the gap. Also watch US index closes, Indian ADRs (Infosys, Wipro, HDFC Bank, ICICI Bank, Dr Reddy's; verify the current list), US 10-year yield and DXY, and Asian markets at the open.
- **Use them** for gap-risk planning on the next open, not for stock selection.
- **Failure:** the gap is fully faded intraday on domestic flows.

### FII/DII flows

- **Where:** NSE provisional cash data after the close; the NSDL FPI daily and fortnightly data, which give sector allocation fortnightly.
- **Use:** as regime context. A streak of heavy FII selling pressures large-cap banks and IT; DII/SIP flows cushion dips. The data does not show causation for a specific stock ([factors and regime](factors-and-regime.md)).

### Sector rotation and relative-strength leadership (`RS_LEADER_IN_WEAK_TAPE`)

- **Detect:**
  - Rank sector indices by 5-, 20- and 60-day RS against Nifty.
  - Within leading sectors, rank stocks by RS and closeness to 52-week highs.
  - `RS_LEADER_IN_WEAK_TAPE`: while Nifty is falling or below its 20/50 DMA, the stock holds above its 50 DMA and makes higher lows with positive RS. These are frequently the first to break out once the market turns.
- **Confirm:** the stock's down days come on lower volume and delivery; it recovers quickly after market-wide down days.
- **Failure:** a defensive rotation (FMCG, pharma) that reverses when risk appetite returns; a leader that finally cracks, which it can do late in a correction.
- **Entry:** a break of the recent pivot high when Nifty stabilises (for example, Nifty reclaims its 20 DMA).
- **Invalidation:** a close below the 50 DMA or the higher-low pivot.

## F&O positioning signals (signal only)

Compute from the F&O bhavcopy, using the aggregate futures OI across expiries for the stock.

| Price | OI | Label | Reading | Scanner |
|---|---|---|---|---|
| Up | Up | Long buildup | New longs; the trend has participation | `LONG_BUILDUP` |
| Down | Up | Short buildup | New shorts; avoid longs | none |
| Up | Down | Short covering | Shorts exiting; the move can be sharp but short-lived | `SHORT_COVERING` |
| Down | Down | Long unwinding | Longs exiting; weakness without fresh shorts | none |

- **Strength:** OI change ≥ ~5–10% day-on-day, with a price move of at least ~0.5 ATR and RVOL > 1.5x. Small OI changes are noise.
- **Rollover %:** next-month OI as a share of total, measured in the last days before expiry. High rollover with rising price supports continuation; low rollover suggests positions are closing. Compare with the stock's own 3-expiry average.
- **Stock PCR (OI):** extremes are contrarian context only, and liquid only in large names.
- **IV:**
  - IV rising into results is normal. IV crush after results means the event was priced.
  - An IV spike without news is a lead to investigate, not a signal.
- **F&O ban:** when OI exceeds 95% of MWPL (verify the current formula; SEBI revised MWPL computation in 2025) no new F&O positions are allowed until OI falls below 80%. For cash trading, ban entry often coincides with an overheated move. Treat banned names as blocked for new picks.
- **Expiry week:**
  - Pinning near high-OI strikes.
  - Rollover-driven volume.
  - Sharp short covering in the last sessions.
  - Avoid reading a signal from expiry-day OI changes.
  - The expiry weekday changed in 2025 and exchanges may change it again. Verify on NSE/BSE circulars.

## Technical setups

### 52-week or all-time-high breakout (`BREAKOUT_52W`)

- **Detect:** the close is above the prior 52-week high (or all-time high) after at least ~3–4 weeks below it.
- **Confirm:**
  - RVOL ≥ ~1.5–2x.
  - Delivery ratio > 1.2–1.5x.
  - The close is in the top quarter of the range.
  - The sector is in the top RS half.
  - In F&O names, long buildup rather than short covering.
- **Failure:**
  - The breakout reverses below the old high within 1–3 sessions.
  - Low-volume breakouts.
  - Breakouts into results.
  - The move is already more than ~3 ATR beyond the level at entry, which means chasing.
- **Entry:** the breakout close, or a retest of the old high that holds.
- **Invalidation:** a close back below the old high by more than ~0.5 ATR.
- **Hold:** 3–10 sessions.

### Base breakout / volatility contraction (`BASE_BREAKOUT_VCP`)

- **Detect:**
  - A base of 3–10+ weeks with successively smaller pullbacks (for example 20% → 10% → 5%).
  - Falling volume in the right side of the base.
  - ATR contracting, with an NR7 (narrowest range of 7 days) or inside day just below the pivot.
- **Confirm:** the break above the pivot comes on RVOL ≥ ~1.5x with a strong close; the prior trend is up (price above a rising 50 and 200 DMA).
- **Failure:** a wide, loose base; a break during a weak market regime; a pivot defined after the fact.
- **Entry:** a buy-stop just above the pivot.
- **Stop:** below the last contraction low, capped at ~1–1.5 ATR.
- **Hold:** 3–10 sessions.

### Pullback in an uptrend (`PULLBACK_UPTREND`)

- **Detect:**
  - Price above a rising 50 and 200 DMA.
  - A 3–7 session pullback on falling volume to the 20 DMA (strong trends) or the 50 DMA (normal trends).
  - Holds above the prior swing low.
- **Confirm:** a reversal bar (close above the prior day's high) with higher volume; delivery higher on the up day than on the pullback days.
- **Failure:** the pullback on rising volume or delivery (distribution); the 50 DMA breaks on a closing basis; the market regime deteriorates.
- **Entry:** above the reversal day's high.
- **Stop:** below the pullback low.
- **Hold:** 3–10 sessions.

### Delivery accumulation in a tight range (`DELIVERY_ACCUMULATION`)

- **Detect:**
  - A range of ≤ ~1.5–2 ATR for 5–15 sessions.
  - Delivery % well above the stock's own 60-day average (for example ≥ 1.5x) on several days.
  - Rising delivered quantity.
- **Confirm:** a break out of the range with volume; a supporting catalyst or ownership filing.
- **Caveat:** delivery shows shares settled, not who bought or why ([expert rules](expert-rules.md) #14). High delivery also occurs on deal days, index trades and pledge movements, so rule those out using the deal files.
- **Invalidation:** the range breaks to the downside.
- **Hold:** until the breakout, then 3–10 sessions.

### Gap holds

- A news gap that holds above the prior day's high for 2–3 sessions without filling tends to show institutional demand. This is the base condition for `EARNINGS_GAP_DRIFT` and `DEAL_FOLLOW_THROUGH`.
- Invalidation is the gap filling.

## Market regime: when to be aggressive and when to sit out

Inputs, from dated data:

- Nifty 50 and Nifty 500 against their 50 and 200 DMA, and the slope of each.
- Breadth: % of Nifty 500 above their 50 DMA.
- Advance/decline ratio over 5–10 sessions.
- New 52-week highs against lows.
- India VIX level and 5-day trend.
- FII cash flow streak.
- Small-cap index relative to Nifty.

| Regime | Typical inputs (configurable) | Behaviour |
|---|---|---|
| Aggressive | Nifty above a rising 50 and 200 DMA; breadth > ~60%; A/D > 1; VIX low or falling; new highs > new lows | Full risk per trade and max positions; favour breakouts |
| Normal | Nifty above the 200 DMA but choppy around the 50 DMA; breadth 40–60% | Half to full risk; favour pullbacks and RS leaders; fewer positions |
| Defensive | Nifty below the 50 DMA, 200 DMA flat; breadth < ~40%; VIX rising | Quarter to half risk; only `RS_LEADER_IN_WEAK_TAPE` and verified catalysts; 1–3 positions |
| Sit out | Nifty below a falling 200 DMA; breadth < ~25%; VIX spiking; heavy FII selling streak | No new longs, or paper-trade only; cash is a position |

The scanner (`python -m stockex.cli scan`) reports `RISK_ON`, `NEUTRAL` or `RISK_OFF` from Nifty 50 against its 50/200 DMA, breadth of the imported universe above its 50 DMA, and India VIX level and 5-day change, and prints the inputs. Read them as Aggressive, Normal and Defensive. In `RISK_OFF` the scanner halves the risk budget and keeps only candidates with positive 20- and 60-day relative strength. It does not emit Sit out: apply that row yourself from the inputs it does not compute (A/D, new highs against lows, FII streak, small-cap relative strength).

The regime label is an observation, not a forecast. Record all inputs. If they conflict, use the more conservative row.

## Trade management rules professionals use

- **Risk per trade:** 0.5–2% of trading capital as a configurable starting point (harness default 1%). Quantity = risk ₹ / (entry − stop). Cap the result by liquidity and by a position-value cap of about 10–20% of capital. The scanner's liquidity default is position value ≤ 2% of the 20-day median traded value (`max_participation`), so a full exit fits comfortably inside one session. The looser 5–10% of ADV rule of thumb suits only very liquid large caps.
- **Stops:** structure-based, placed below the pivot, gap low or swing low. Bound them by ATR: a structure stop more than ~2–3 ATR away is too loose, and one under ~1 ATR is noise-prone. The scanner widens stops tighter than 1× ATR(14) to 1× ATR and rejects stops wider than 3× ATR (both configurable). Decide the stop before entry and never widen it.
- **Targets:** T1 at about 1.5R, where you scale out a third to a half and move the stop to breakeven or the last higher low. T2 at about 3R or the next resistance or measured move. Trail the rest under the 10/20 DMA or prior-day lows. The backtester models this as: sell half at T1, move the stop to the entry price, trail the rest under the lower of the last two sessions' lows, exit everything at T2 or the setup's time stop.
- **R:R after costs:** include brokerage, STT, exchange and SEBI charges, GST, stamp duty, DP charge and slippage. Reject if planned R:R to T2 after costs is below the mandate's minimum (default 2:1).
- **Time stop:** exit if the trade has not reached +1R within ~3–5 sessions, or at the mandate's maximum holding period. Dead money is risk.
- **Never average down.** Add only to winners at a new valid entry, with the combined position respecting risk limits.
- **Gap and circuit risk:** overnight gaps can jump the stop. Price bands of 2/5/10/20% (non-F&O stocks) can lock you in; F&O stocks have dynamic bands. Size so that a gap of about 2x the planned stop distance is survivable. Avoid holding illiquid names through results.
- **Portfolio limits (configurable):** max concurrent positions of 3–8; no more than 2 positions or ~30% of risk in one sector; open risk (sum of distances to stops) ≤ ~5–6% of capital.
- **Loss limits:** stop opening trades for the day after about −2R to −3R, and for the week after about −5R to −6R. Review before resuming.
- **Block list:** ASM/GSM stages, trade-for-trade (T2T/BE series), F&O ban, SME platform (unless opted in), stocks in the 2% or 5% band with frequent circuits, traded value below the mandate floor, and pending results inside the holding window unless the trade is explicitly a results trade.
- **Journal every trade:** setup, scanner, catalyst source, entry, stop, exits, R multiple, costs and a rule-adherence note. Feed the log back into the scorecard ([post-mortem](../templates/post-mortem.md)).
