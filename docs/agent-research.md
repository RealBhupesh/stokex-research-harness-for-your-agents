# Auditable agent research

The executable synthesis contract accepts research produced by agents or people;
it does not invent reports or invoke an LLM. Five specialist roles supply findings:
`fundamentals`, `valuation`, `market`, `risk` and `legal_credit`. An independent
skeptical reviewer must review every finding. Use the existing specialist skills
to perform the research, then submit the typed records to the deterministic gate.

Each specialist report binds to the same `evidence_digest`, names its reviewer,
and cites packet source and observation IDs. Unknown references, missing roles,
failed work, stale digests, unverified or unavailable observations, unresolved
concerns and incomplete skeptical review block consideration. The skeptic's
reviewer ID must differ from all specialist reviewers. Reviewer IDs are assertions;
the harness cannot authenticate who performed the work or whether the supplied
packet omits important evidence.

The [research module](../stockex/research.py) documents the exact input contract.
The [synthetic fixture](../tests/fixtures/research-synthesis.json) demonstrates the
shape; it is not research on a real issuer and is not evidence of investment merit.

```bash
stockex research-synthesize research-input.json --out /data/research-run-001
stockex research-verify /data/research-run-001
```

The output directory must be new. A bundle contains frozen `input.json`,
`result.json` and a final `manifest.json` of SHA-256 hashes. A failed gate still
writes an inspectable `BLOCKED` bundle and returns exit code 3. A crash before
the final manifest leaves an incomplete bundle, which does not verify. Verification
checks hashes and repeats synthesis from frozen inputs. A valid blocked bundle
can verify: content integrity and research eligibility are different questions.
Hashes and replay do not authenticate sources or prevent a malicious person from
replacing the entire bundle with different internally consistent inputs.

Instead of a prebuilt `evidence_packet`, the input may specify an evidence-store
configuration under `evidence`:

```json
{
  "evidence": {
    "database": "/data/evidence.sqlite3",
    "security_id": "YOUR_STABLE_SECURITY_ID",
    "cutoff": "2026-10-13T13:00:00Z",
    "fields": ["financial.revenue", "financial.operating_cash_flow"],
    "metadata": {
      "issuer": "Verified issuer name",
      "symbol": "VERIFIED_SYMBOL",
      "exchange": "NSE"
    },
    "mandate": {
      "mode": "LONG_TERM_COMPOUNDING",
      "horizon": "5 years",
      "personalized_sizing": false
    }
  },
  "reports": [],
  "skeptical_review": {}
}
```

This incomplete example intentionally blocks until actual cited reports and
review are supplied. Relative database paths resolve beside the input file.
Store conflicts and requested-field gaps are retained as controlling evidence,
not discarded when selecting a convenient observation. Reconcile them with new
source evidence before building a new review iteration. The observation quality
label `VERIFIED` is itself supplied evidence metadata, not an independent audit.

Personalized sizing, aggressive short-term and speculative mandates also require
their existing portfolio/trade/speculation controls in the builder's hash-bound
`decision_context`. A successful gate means supplied records consistently support
consideration under this contract. It does not authorize orders or certify returns.
