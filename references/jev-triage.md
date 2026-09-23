# Jev evidence triage

Jev is TypeSafe AI's "System One" decision model. It does not write text. It
evaluates a state against typed questions and returns calibrated answers:
`noul` (probability of yes), `choice` (one option with per-option
probabilities) and `score` (an ordered level with a distribution). STOCKEX uses
it to triage evidence-room sources quickly and repeatably before an analyst
reads them in depth.

**Triage is advisory.** It never changes the evidence packet, stored records,
gates, research status or `scripts/decision_packet.py` results. A flag asks for
a check; it is not a finding. Resolve every flag against the primary source
before a gate that depends on that evidence can pass.

## Running it

```text
export TYPESAFE_API_KEY=...
python -m stockex.cli packet DATABASE SECURITY_ID --cutoff TIMESTAMP
python -m stockex.cli jev-triage DATABASE SECURITY_ID --cutoff TIMESTAMP \
  --excerpts excerpts.jsonl [--confidence-floor 0.7] [--model jev-latest]
```

`excerpts.jsonl` holds one `{"source_id": "...", "text": "..."}` object per
line. The store keeps source metadata, not document text, so supply the
relevant extract of each filing. Only sources in the cutoff packet are sent to
Jev. Excerpts for other sources are listed under `ignored_excerpts` and never
leave the machine. Keep excerpts to text that was available by the cutoff.

## Question bank (version 1)

Each packet source is asked:

- `source_class` (choice): primary_filing, exchange_disclosure, regulator,
  company_communication, sell_side, news, social, other.
- `claim_type` (choice): verified_fact, management_claim, analyst_opinion,
  rumour.
- `materiality` (score): immaterial, minor, material, controlling.
- `forward_looking` (noul).
- `restatement_or_amendment` (noul).

Each store conflict (observations of the same field and validity time that
disagree) is asked `contradicts` (noul): is the difference substantive rather
than units, basis, rounding or restatement?

Changing a question changes `question_bank_version`, so old and new reports
are never compared as if they were the same measurement.

## Flags

| Flag | Meaning | Required action |
| --- | --- | --- |
| `LOW_CONFIDENCE` | Confidence (or selected-option probability) is below the floor. Dependent flags are suppressed. | Classify the source manually. |
| `SOURCE_CLASS_MISMATCH` | The declared `source_class` is a bank label and Jev confidently picked a different one. | Confirm the originator. A misclassified source cannot carry primary-evidence weight. |
| `CLAIM_NOT_FACT` | A material or controlling source reads as a claim, opinion or rumour. | Verify against a primary filing or downgrade it to perception evidence. |
| `POSSIBLE_RESTATEMENT` | The source may amend or withdraw earlier data. | Check vintages and revision links in the store. |
| `SUBSTANTIVE_CONFLICT` | A store conflict looks substantive. | Add it to the contradiction ledger as unresolved. |
| `LIKELY_NON_SUBSTANTIVE` | A store conflict looks like units, basis or rounding. | Still reconcile it; Jev only ranks it lower. |
| `METADATA_ONLY` | No excerpt was supplied, so only metadata was judged. | Supply the text if the source matters. |
| `JEV_UNAVAILABLE` | The call failed for that item. | Treat it as a gap, not as negative evidence. |

`review_queue` lists every item that needs human attention, in packet order.

## Recording and calibration

Each item carries `input_sha256` over the exact state sent, and the report
records `jev_models`, `question_bank_version`, `confidence_floor` and
`generated_at`. Keep reports next to the decision journal so that later
reviews can compare Jev judgments with what the primary sources showed, and
tune the floor from that record instead of assuming vendor calibration.

## Limits

- Calibration and accuracy claims are the vendor's. They have not been tested
  here on Indian filings.
- The `score` request encoding (levels sent as ordered `criteria`) must be
  confirmed against `https://docs.typesafe.ai/api` before live use.
- Excerpts go to a third-party API. Do not send licensed, confidential or
  personal data without the right to do so.
- Triage cannot establish source authenticity, completeness or investment
  merit.
