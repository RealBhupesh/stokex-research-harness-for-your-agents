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

## NSE end-of-day files for market import

Download these for each session and load them with `python -m stockex.cli market-import DATABASE FILES...`. Check coverage with `python -m stockex.cli market-status DATABASE`.

| File | Pattern | Provides |
|---|---|---|
| Full bhavcopy with delivery | `sec_bhavdata_full_DDMMYYYY.csv` | OHLC, prev close, volume, turnover, delivered quantity, delivery % by series |
| UDiFF CM bhavcopy | `BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv` | Cash-market OHLCV in the UDiFF format with ISIN |
| UDiFF F&O bhavcopy | `BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv` | Futures and options OHLC, settlement, OI, change in OI, by expiry and strike |
| Corporate actions | NSE corporate actions export (columns include `SYMBOL`, `PURPOSE`, `EX-DATE`) | Splits, bonuses and consolidations used to back-adjust prices |
| Index constituents | e.g. `ind_nifty500list.csv` (`Company Name, Industry, Symbol, Series, ISIN Code`) | Symbol-to-industry map for sector strength and sector caps |
| Corporate announcements | NSE announcements export (`SYMBOL`, `SUBJECT`, `DETAILS`, `BROADCAST DATE/TIME`) | Results, orders, buybacks and other catalysts, classified on import |
| Index closing values | `ind_close_all_DDMMYYYY.csv` | Nifty, sector and strategy index closes for benchmark and RS |
| Bulk deals | bulk-deals CSV | Client name, buy/sell, quantity, price |
| Block deals | block-deals CSV | Same, for the block window |
| Surveillance lists | ASM and GSM lists | Security-level surveillance stage |
| F&O ban list | securities-in-ban-period file | Securities where new F&O positions are barred |

All of these are on nseindia.com under "All Reports" (equities and derivatives, daily) and the market-data and surveillance pages. NSE reorganises pages and renames files, so verify locations and column layouts at use time. Downloads are manual, or done in the agent's browser session. The harness does no automated scraping. Keep each file's download time and the session date it represents.

Examples to evaluate, not required subscriptions: Screener.in for discovery, TradingView for chart review, Kite Connect for authorized market data. Check current pricing, entitlements, licensing, adjustments and API documentation before choosing. This package does not implement those integrations or presume any connector is connected. US-focused finance tools are not an automatic substitute for NSE/BSE coverage. A search-result snippet is not a complete filing.

Use read-only routes. Do not request trading permissions for research. Keep API secrets in the platform secret store or environment, redact logs, never embed them in Markdown. Rate-limit and cache permitted requests; distinguish cache date from market date. A failed read means unavailable for this run. User-provided CSVs must retain vendor, extraction time and data definitions.

Use `scripts/finance_helpers.py` for position arithmetic and DCF. It does not validate source accuracy, taxes or suitability. Other calculations must be reproducible in the financial worksheet. Do not install unrelated plugins or scrape restricted endpoints to appear more capable.
