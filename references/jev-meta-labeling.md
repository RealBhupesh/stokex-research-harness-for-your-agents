# Jev meta-labeling for short-term picks

The scanner's setups decide *what* could be traded. Jev, TypeSafe AI's calibrated decision model, decides whether *this instance* is worth taking. This is meta-labeling: a second model filters and ranks a primary signal instead of replacing it. Jev earns influence the same way a setup does. It must be measured out of sample first. Until then it is shown and has no effect.

## What Jev is asked (question bank v1)

| Question | Type | Use |
| --- | --- | --- |
| `follow_through` | yes/no probability | Chance the trade reaches T1 (+1.5R) before its stop, within the time stop. This is the meta-label. |
| `catalyst_quality` | score: none / weak / moderate / strong | Context in the trade-ideas table |
| `crowding_risk` | yes/no probability | Shown as "crowded" when ≥ 0.6 |
| `failure_mode` | choice | Most likely reason the trade fails |

Changing any question bumps the bank version. Proof measured on another version, or on another Jev model, does not carry over.

## Anonymized state

Jev sees only:
- ratios: entry, stop and targets as a percentage from close; returns; relative strength; volume and delivery ratios; ATR %; distance from moving averages and the 52-week high;
- the F&O quadrant and OI changes;
- the regime label and its inputs;
- the setup name and its numeric evidence;
- the catalyst *type* and whether it is verified;
- a liquidity bucket.

It never sees the symbol, any date, client names or absolute prices. Without that rule a backtest could reward Jev for remembering what a well-known stock did on a well-known day.

## How Jev is proven

```bash
python -m stockex.cli backtest market.sqlite3 --from 2025-10-01 --to 2026-08-31 --jev --out scorecard.json
```

Every filled backtest trade is judged, and its outcome (`t1_hit`) is recorded. The scorecard's `jev` section reports:
- **Brier score** against the setup's own T1 base rate, and the resulting **Brier skill** (above 0 means better calibrated than the base rate);
- **AUC** (how well Jev ranks winners above losers; 0.5 is random);
- a **reliability table** (predicted against observed hit rate in five buckets);
- **filtered versus unfiltered expectancy**: average R of trades Jev rated at or above the setup base rate, against all trades.

Jev is `PROVEN` only with at least 50 judged trades, positive Brier skill, AUC above 0.55 and higher filtered expectancy. Otherwise it is `UNPROVEN`, and the reasons are listed.

## What changes in a scan

```bash
python -m stockex.cli scan market.sqlite3 --as-of 2026-09-22 --scorecard scorecard.json --jev --format md
```

- **PROVEN** (same bank version and model):
  - a candidate whose `follow_through` is below its setup's T1 base rate is rejected with `JEV_FILTERED`;
  - the rest gain a `jev_edge` component worth 20% of the score.
- **UNPROVEN or no Jev section:** the Jev column is shown for information, and the order is exactly what it would be without Jev.

Proven setups still rank above unproven ones. Jev never overrides the hard risk plan, restrictions or liquidity rules.

## Cost and caching

Judgments are cached in the market database (table `jev_judgments`), keyed by input hash, bank version and model, so re-running a backtest makes no new calls. `--jev-max-calls` (default 2000) caps new calls per backtest. Trades beyond the cap stay unjudged and are counted. A failed call is recorded as `JEV_UNAVAILABLE`, which is a gap, not a negative judgment. Calls need `TYPESAFE_API_KEY`.

## Limits

- Calibration and accuracy claims are the vendor's until your own scorecard shows them.
- Anonymization reduces memorization but cannot rule out every hint, such as a distinctive combination of moves. Prefer a backtest window after the Jev model's training cutoff.
- A PROVEN status describes the measured period and regime mix. Re-run the backtest regularly and after any model change.
- Jev is advisory for long-term research ([evidence triage](jev-triage.md)). Only the short-term filter uses it for ranking, and only under the rules above.
