# Read-only Upstox daily data

The optional adapter follows the [official V3 daily-candle contract](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/).
It calls only the historical-candle GET endpoint, with explicit instrument keys
and a runtime `UPSTOX_ACCESS_TOKEN`. It has no order, account or portfolio methods.
Configure the token securely in your runtime; do not put it in the manifest,
repository, command arguments or reports. Obtain authorized API access through
the provider's [authentication process](https://upstox.com/developer/api-documentation/authentication/).

```bash
stockex provider-sync /data/market.sqlite3 /data/instruments.json \
  --from 2026-01-01 --to 2026-10-13 --raw-dir /data/provider-raw
```

Use the [instrument manifest schema](../schema/upstox-instruments.schema.json).
Each equity entry requires `type: "equity"`, a verified exchange `symbol`, `isin`,
`series`, and an `instrument_key` equal to `NSE_EQ|` followed by that ISIN.
Each index entry requires `type: "index"`, an explicit `index_name` used by the
harness, and an `NSE_INDEX|...` instrument key. Obtain mappings and series from
current primary instrument records. The provider's equity segment name does not
establish that a security trades in EQ series; the manifest must supply it.

One request covers up to 3650 days per instrument. The adapter validates
timezone-aware daily timestamps, OHLC envelopes, quantities, duplicate sessions
and requested range before publishing a batch. It accepts only candles dated
strictly before the retrieval date in IST, avoiding an unverified current-day
completion assumption. It spaces requests, bounds response sizes, retries
transient failures at most twice, caps Retry-After delays, rejects redirects and
omits raw error bodies. Rate limits and account entitlement still belong to the
provider; the adapter cannot guarantee account-specific availability.

Raw response bytes are retained by SHA-256. Successful `provider_downloads`
entries bind the response hash, request range, instrument, mapping-manifest hash,
retrieval time and inserted-row counts. Responses retained from a failed batch
are diagnostic artifacts, not proof of a successful database import. Tokens and
authorization headers are never part of the audit record. Retain your mapping
manifest alongside the raw responses.

The adapter does not fabricate delivery quantities, traded value, previous close,
surveillance coverage or corporate actions. Identical prices preserve their first
observed availability on subsequent downloads. Conflicting corrections require
an explicitly reconciled new dataset vintage; they are not silently overwritten.

## Separate the price session from research time

Historical candle timestamps mark the candle start, not the time the data became
knowable. Imported rows therefore become available at retrieval. For research
performed later than the price session, explicitly provide the knowledge cutoff:

```bash
stockex scan /data/market.sqlite3 --as-of 2026-10-13 \
  --cutoff 2026-10-14T10:00:00Z
```

Only session dates through `--as-of` and publications through `--cutoff` are
eligible. Default historical backtests retain their original daily cutoffs;
this option cannot make a fresh historical download usable in a prior-day test.
Retrospective scans also do not become forward-test journal evidence.

## Price basis remains an explicit gate

The reviewed provider documentation does not establish the adjustment basis of
every historical candle. Downloads are marked `UNVERIFIED_PROVIDER_HISTORY`.
Combining already-adjusted history with independent corporate actions could
double-adjust prices. Accordingly, strict data health blocks these instruments
until the price basis is reconciled against primary raw price and corporate-action
vintages. The current release has no command that certifies that reconciliation;
keep this adapter experimental and retain the raw inputs. A normal exploratory
scan can inspect the data, but does not resolve this gate.

Tests use documented response-shaped fixtures and injected transports. No live
account request or licensed dataset reconciliation has been performed. Passing
those tests establishes the local contract, not a working account, complete NSE
coverage, contemporaneous historical availability or profitable signals.
