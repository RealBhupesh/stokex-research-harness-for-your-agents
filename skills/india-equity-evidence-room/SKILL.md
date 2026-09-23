---
name: india-equity-evidence-room
description: Build and audit a point-in-time evidence packet for an NSE or BSE company before forecasts, valuation or recommendation.
---
# India Equity Evidence Room

Read [evidence gates](../../references/evidence-gates.md), [point-in-time rules](../../references/point-in-time.md) and [financial normalization](../../references/financial-normalization.md). Use [the operating system](../../references/research-operating-system.md) to identify the required downstream gates.

Resolve issuer, ISIN, exchange and security first. Gather primary filings, preserve availability timestamps and separate extracted facts from analyst inference. Build a contradiction ledger and reconcile reported financial statements before permitting forecasts.

Return an evidence packet, normalized-history worksheet, unresolved conflicts and `PASS`, `PASS_WITH_LIMITS` or `FAIL`. Missing controlling evidence produces `INSUFFICIENT DATA`, not an estimate. Do not infer unavailable facts from price action or secondary summaries.

## Database-backed packet

If a STOCKEX SQLite database is supplied, require a stable security ID or ISIN and the user-specified cutoff timestamp. Before any forecast, valuation or opinion, run:

```text
python -m stockex.cli packet DATABASE SECURITY_ID --cutoff TIMESTAMP
```

Use the resulting point-in-time packet as the evidence-room input, then run:

```text
python -m stockex.cli integrity DATABASE
```

Treat `valid=true` as internal consistency only. It does not establish source authenticity, dataset completeness, investment suitability or predictive power. If no database is supplied, preserve the manual primary-source evidence ledger and contradiction workflow above. Preserve `INSUFFICIENT DATA` when controlling evidence is unavailable; follow the linked point-in-time reference for detailed vintage and timestamp rules.

## Optional Jev triage

When a `TYPESAFE_API_KEY` is available, run advisory triage after the packet and before reading sources in depth:

```text
python -m stockex.cli jev-triage DATABASE SECURITY_ID --cutoff TIMESTAMP --excerpts EXCERPTS.jsonl
```

Work every `review_queue` item as described in [Jev triage](../../references/jev-triage.md). Flags are prompts to check, not findings. They never pass or fail a gate. A `SUBSTANTIVE_CONFLICT` enters the contradiction ledger, a `CLAIM_NOT_FACT` on material evidence needs primary verification, and `JEV_UNAVAILABLE` is a gap. Without a key, skip triage; the workflow above is unchanged.
