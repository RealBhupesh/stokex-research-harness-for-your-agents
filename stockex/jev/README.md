# Jev wire contract and research adapter

The client follows [TypeSafe's published API](https://docs.typesafe.ai/api), verified on 2026-10-14. No authenticated provider calls were made during contract testing.

Research question banks declare score rubrics as ordered maps of stable labels to descriptions. The HTTP client sends the descriptions as an ordered array of 2–10 levels. A provider score response contains a numeric probability-weighted level, a numeric-indexed legend and distribution, and confidence. Choice responses contain every requested option and its probability, plus the highest-probability choice and confidence. Distributions must sum to one within 0.000001; score and legend must agree with the requested rubric and distribution.

The client preserves the provider's numeric `score`, `legend`, and numeric-indexed `probabilities`. It adds `level_probabilities`, indexed by the research rubric labels, and `level`, the uniquely most probable label. A tie produces `level: null`; the expected score is never rounded into an invented categorical decision. Advisory evidence triage treats a tied materiality level as low confidence. Candidate summaries preserve both the symbolic `catalyst_quality` (possibly null) and numeric `catalyst_quality_score`.

This changes response semantics: evidence report schema, evidence question bank, and candidate question bank are version 2. Candidate caches and calibration proofs from version 1 must not be reused. Regenerate them before filtering candidates with Jev. Provider models and confidence remain unproven for Indian equities until measured on an appropriate held-out sample.

Tests inject provider-shaped JSON through the real client and exercise triage, candidate summaries and caching without network access. HTTP 529 joins 429 and transient server failures in the bounded retry policy. Paid live endpoint behavior and provider entitlement remain deployment checks.
