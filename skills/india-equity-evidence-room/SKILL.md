---
name: india-equity-evidence-room
description: Build and audit a point-in-time evidence packet for an NSE or BSE company before forecasts, valuation or recommendation.
---
# India Equity Evidence Room

Read [evidence gates](../../references/evidence-gates.md), [point-in-time rules](../../references/point-in-time.md) and [financial normalization](../../references/financial-normalization.md). Use [the operating system](../../references/research-operating-system.md) to identify the required downstream gates.

Resolve issuer, ISIN, exchange and security first. Gather primary filings, preserve availability timestamps and separate extracted facts from analyst inference. Build a contradiction ledger and reconcile reported financial statements before permitting forecasts.

Return an evidence packet, normalized-history worksheet, unresolved conflicts and `PASS`, `PASS_WITH_LIMITS` or `FAIL`. Missing controlling evidence produces `INSUFFICIENT DATA`, not an estimate. Do not infer unavailable facts from price action or secondary summaries.
