# Tool plan and fallbacks
| Job | Preferred tool/source | Fallback and constraint |
|---|---|---|
| Find disclosures | NSE/BSE corporate filings, issuer IR | Browser/search, then user-supplied PDF; verify issuer |
| Screen universe | Dated exchange universe plus authorized fundamentals export | Discovery screen with explicit coverage gaps |
| Daily OHLCV | NSE reports or licensed broker/data export | Dated CSV, verified action adjustments |
| Current quotes | Authorized read-only broker/provider API | Timestamped exchange quote; no live trade plan if absent |
| Macro | RBI statistics and official releases | Named official publication; period must match |
| Statements | PDF/table tools and Python | Manual visual inspection and source-linked worksheet |
| Models | Python or spreadsheet tools | Transparent formulas with unit checks |
| Technical charts | Actual dated OHLCV with plotting library | Explain missing chart, do not invent candles |
| Archive and tracking | Markdown files, source ledger and decision journal | User-owned local export |

Examples to evaluate, not required subscriptions: Screener.in for discovery, TradingView for chart review, Kite Connect for authorized market data. Check current pricing, entitlements, licensing, adjustments and API documentation before choosing. This package does not implement those integrations or presume any connector is connected. US-focused finance tools are not an automatic substitute for NSE/BSE coverage. A search-result snippet is not a complete filing.

Use read-only routes. Do not request trading permissions for research. Keep API secrets in the platform secret store or environment, redact logs, never embed them in Markdown. Rate-limit and cache permitted requests; distinguish cache date from market date. A failed read means unavailable for this run. User-provided CSVs must retain vendor, extraction time and data definitions.

Use `scripts/finance_helpers.py` for position arithmetic and DCF. It does not validate source accuracy, taxes or suitability. Other calculations must be reproducible in the financial worksheet. Do not install unrelated plugins or scrape restricted endpoints to appear more capable.
