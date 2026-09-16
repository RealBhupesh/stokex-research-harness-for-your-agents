# Point-in-time evidence contract

Every historical decision or backtest must reconstruct only information available at the decision timestamp. Reference period is not availability time. A March quarter reported in May is unavailable to an April decision.

## Required fields

For each observation retain: issuer/ISIN, field name, value and units, period start/end, source document ID, exchange broadcast or verified availability timestamp in IST, retrieval timestamp, revision ID, original/revised status, and `valid_until` when known. For prices retain exchange session, adjustment state and corporate-action version. For universe membership retain effective-in and effective-out dates.

## Selection rule

At a decision timestamp `T`, use the latest authoritative observation whose `available_at <= T`. If a later restatement is used for a live current decision, label it revised. Never overwrite the historical vintage used in an earlier prediction. If `available_at` is unknown, the item cannot enter a strict point-in-time backtest.

## Joins and lags

- Join issuer data by stable identifier, not ticker alone.
- Apply a conservative publication lag only when the true broadcast timestamp cannot be obtained, and disclose that this is an assumption.
- Never forward-fill an observation beyond a known superseding filing, delisting, merger or accounting-basis change.
- Use constituents actually eligible at each rebalance, including later delisted or failed companies.
- Preserve revised and original filings as separate vintages. A correction can be decision-relevant information itself.
- Historical LLM analysis is not automatically point-in-time because the model may remember later outcomes. Restrict it to the supplied vintage packet and do not ask it to recall later facts.

## Gate

Live research may proceed with clearly dated current evidence. A performance claim, learned weight or historical hit rate is BLOCKED until the dataset passes availability, universe, corporate-action, delisting and cost checks. Run `scripts/decision_helpers.py point_in_time` on structured records as a basic timestamp check; it does not prove dataset completeness.

## Local executable workflow

The first executable release is an offline local SQLite evidence store. It
uses only records supplied by the user or an approved provider adapter. It
does not scrape exchanges or guarantee source authenticity or completeness.
Use these commands from the repository root:

```bash
python -m stockex.cli init research.sqlite3
python -m stockex.cli ingest research.sqlite3 evidence.jsonl
python -m stockex.cli packet research.sqlite3 INE000A01001 --cutoff 2026-06-01T10:00:00+05:30
python -m stockex.cli integrity research.sqlite3
```

`packet` reconstructs the evidence eligible at the cutoff. `integrity`
checks internal consistency only. A valid report does not establish that the
underlying sources are authentic or that the dataset is complete enough for a
backtest or investment decision.
