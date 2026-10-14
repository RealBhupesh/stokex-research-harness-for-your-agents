# Operating the STOCKEX harness

This release strengthens the existing offline Indian-equity and Jev integration.
It provides local operational controls; it does not establish production data
coverage, source authenticity or profitable trading performance. No broker,
paid feed, account or order execution is connected by installation.

## Install and verify

Python 3.10+ and SQLite are required. No third-party runtime dependencies are
required. Create a virtual environment outside the checkout, then install:

```bash
python3 -m venv /tmp/stockex-venv
/tmp/stockex-venv/bin/python -m pip install .
/tmp/stockex-venv/bin/stockex --help
python3 -m unittest discover -s tests -q
```

CI runs the test suite on Python 3.10–3.14, builds a wheel, installs it, and
checks the CLI from outside the repository. The research skills and reference
documents remain repository assets, separate from the installed Python modules.
Packaging follows the [Python packaging guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).

## Provider integration contract

The supported market-data interface is a batch of supplied NSE-format CSV files.
An upstream licensed provider, manual download or existing agent can deliver
those files. STOCKEX does not bypass exchange access controls or scrape pages.
Retain the original files and their publication timestamps in your own data
storage. The supported formats are listed by `stockex market-import --help`.

```bash
stockex market-import /data/market.sqlite3 /data/session/*.csv
stockex market-status /data/market.sqlite3
stockex market-health /data/market.sqlite3 --as-of 2026-09-22 --min-symbols 100 --min-history 61
```

All files in one invocation commit together. A malformed later file rolls back
earlier files and their audit entries. SQLite schema initialization is separate
from the data batch. Call `import_market_batch(connection, paths, **options)`
from Python for the same behavior; nested calls preserve the caller's transaction.

`market_imports` preserves the original content ledger. Schema v3 adds
`market_import_runs`, keyed by the content hash, detected kind and normalized
series, option-retention, availability and index-name settings. A repeated run is
idempotent. Different retention settings can legitimately process the same input
again. Row counts and skip reasons are retained for each successful run; failed
batches report a structured error and leave no successful-run entries behind.
Capture stderr and the exit status in the calling job for failed-run history.

Availability is a point-in-time assertion, not a download timestamp. The default
for daily prices is the existing 13:00 UTC assumption. Use `--available-at` when
the real publication time differs, and import files with different publication
times in separate invocations. The flag applies to every file in its invocation.
Changing availability for previously recorded content is rejected. Bars with
conflicting OHLCV or different availability cannot be silently merged. Retain
separate database vintages for corrections and later enrichment. Some other
market tables still replace matching keys; this is not an immutable, bitemporal
market-data lake. Use the evidence store for append-only sourced observations.

For index constituent files, `--available-at` determines the snapshot date.
Without it, the import date is used. Supply a historical timestamp only when
you have evidence the snapshot was available then. Sector strength and candidate
classification now use only snapshots dated by each evaluated session. This
does not reconstruct a survivorship-free exchange universe or intraday snapshots.

Schema v4 additionally records publication availability for corporate actions
and restrictions. Legacy rows become available at migration time, because their
historical availability cannot be established from the old schema. Supply
verified source vintages in a fresh database for historical studies.

Pre-v3 imports lack their original option settings. They are preserved, but the
first reimport records the settings you supply now. Rebuild from retained source
files if the earlier settings or availability are uncertain.

## Gate unattended scans

```bash
stockex scan /data/market.sqlite3 --as-of 2026-09-22 \
  --scorecard /data/scorecard.json --strict-data --min-symbols 100 --journal
```

`--strict-data` checks SQLite integrity, cutoff-eligible bars for the exact
requested session, minimum symbol coverage, at least 61 distinct historical
sessions for the configured minimum number of current symbols, price and delivery
consistency, and current NIFTY 50 coverage. A failure returns a JSON `BLOCKED`
report, no candidates, no journal writes and exit code **3**, including when
Markdown was requested. The standalone `market-health` command defaults to 60
sessions; use `--min-history 61` to match the scanner's warm-up requirement.

Set `--min-symbols` for your expected dataset; its default of one only protects
against an empty universe. Insufficient history for some other symbols is still
handled by the scanner. Missing delivery, surveillance and corporate-action
records produce warnings. Empty restriction data cannot prove no restriction
exists, and a passing health report cannot establish complete coverage. The
operator must verify these sources before using research outputs.

The session is explicit so holiday and missing-file decisions belong to the
calling workflow. It does not guess the latest exchange session from weekdays.
Exploratory scans remain available without `--strict-data`.

Scorecards must contain `period.to` and `period.data_through`, both strictly
earlier than the scan date. Later exit observations count as outcome data even
when the last signal is earlier. Rejection happens before candidate evaluation
or paid judge calls. Positive mean returns without an explicit statistical
`PROVEN` status and positive confidence bound no longer earn a proven label.
Scorecards are trusted local artifacts; these checks do not authenticate them.

## Jev API behavior

The existing optional Jev integration uses `TYPESAFE_API_KEY` and requires an
HTTPS endpoint without embedded credentials. Requests have a finite positive
timeout. The built-in transport rejects redirects, caps responses at 2 MiB,
and makes at most two attempts, with a short delay before retrying transient
errors. Provider error bodies are omitted from CLI errors to avoid echoing
credentials or sensitive data. Keep the key in your runtime's secret facility.

No live Jev request was made during this change. Stubbed transport and calibration
tests validate local behavior; they do not establish current API compatibility,
model quality or a subscription. Preserve model IDs and question-bank versions
with research artifacts. A model's opinion earns ranking influence only under
the existing measured-proof gates.

Typed scores follow the provider's ordered-array request and numeric response
contract. Numeric expected scores and explicit modal labels are retained
separately. A tied mode has no categorical label. Question-bank version 2
invalidates cached judgments produced under the earlier incompatible contract.

Backtests now build the signal universe at each day's cutoff and use separate
future exit histories. Partial exits update both cash and remaining shares on
their actual dates. Unresolved outcomes are excluded from performance proof and
training. Setup proof requires enough distinct sessions and disjoint day folds;
schema-3 scorecards invalidate the earlier statistical contract.

## Back up and restore

Use different files for the market database and point-in-time evidence store.
They have incompatible corporate-action schemas; accidental mixed use is now
rejected before schema installation.

```bash
stockex backup /data/market.sqlite3 /backups/market-2026-09-22.sqlite3
stockex backup /data/research.sqlite3 /backups/research-2026-09-22.sqlite3
```

Backups use SQLite's online backup API, verify `PRAGMA integrity_check`, flush the
file, and publish it without overwriting an existing destination. The result
includes a SHA-256 checksum. A temporary file is removed on failure. The destination
directory must already exist and support hard links. See the
[SQLite Python API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).

Restore to a new path, verify its checksum against the saved job output, then
run `market-status` and `market-health` for market data or `integrity` for evidence.
Test restore procedures on copies before replacing an operational database.
Keep off-machine backups and original input files. The CLI does not schedule
backups or implement retention, encryption or offsite storage.

Scorecard JSON output is written to a temporary file, flushed and replaced only
after complete serialization. A failed write preserves the previous report.

## Exit codes and deployment boundary

| Code | Meaning |
| --- | --- |
| 0 | Command completed; still inspect warnings and research qualifications |
| 2 | Invalid arguments, import failure, API failure, filesystem or SQLite error |
| 3 | Data health blocked the requested session |

Run this as a CLI job on a local durable filesystem. SQLite is suitable for this
local workflow, with serialized ingestion and bounded lock waits. There is no
multi-user API, tenant isolation, broker execution, distributed scheduler or
server authentication layer in this release. Do not expose the SQLite files or
CLI as an unauthenticated service.

Before deployment with financial consequences, supply and validate a licensed
historical/live feed, retained publication times, corporate-action vintages,
historical membership and delistings, exchange calendars and surveillance-list
coverage. Benchmark the complete strategy on untouched data and forward journal
results. Monitor missing batches, skipped rows, changing coverage, API failures
and backup checksums. Choose thresholds and retention policies explicitly.
