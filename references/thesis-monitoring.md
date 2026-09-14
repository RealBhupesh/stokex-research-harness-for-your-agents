# Thesis monitoring

Freeze the original thesis, forecasts, scenario ranges, price, evidence cutoff, risks, catalysts, invalidation rules and decision status. New evidence creates a new version. Never overwrite the original record.

Classify new information as confirms thesis, weakens thesis, invalidates thesis, changes valuation only, changes timing only, changes risk or exit capacity, or irrelevant noise. Every status change requires a dated source, reason and affected assumption.

Valid states are `ACTIVE`, `CONFIRMED`, `WEAKENED`, `INVALIDATED` and `CLOSED`. An invalidated thesis can only close. Reopening requires a new thesis ID and fresh decision packet.

Use [active research triggers](active-research-triggers.md) to rerun affected stages. A price decline alone does not invalidate a fundamental thesis, and a gain does not confirm it. Compare new evidence with the predeclared prove and kill conditions.

Without a configured feed or automation, provide a manual review calendar and never claim continuous monitoring.
