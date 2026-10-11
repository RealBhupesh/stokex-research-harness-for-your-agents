"""Write small CSV files in NSE end-of-day layouts for tests."""

from datetime import date, timedelta


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

CM_FULL_HEADER = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE,"
    " AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER"
)
UDIFF_HEADER = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
    "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
    "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
    "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4"
)
INDEX_HEADER = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,Closing Index Value,"
    "Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield"
)
DEALS_HEADER = "Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks"


def nse_date(day: date) -> str:
    return f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year}"


def weekdays(start: date, count: int) -> list[date]:
    days, current = [], start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def cm_full_line(symbol, day, o, h, l, c, prev, volume, deliv_pct=None, series="EQ"):
    turnover_lacs = c * volume / 100_000
    deliv_qty = "-" if deliv_pct is None else str(int(volume * deliv_pct / 100))
    deliv_per = "-" if deliv_pct is None else f"{deliv_pct:.2f}"
    return (
        f"{symbol}, {series}, {nse_date(day)}, {prev:.2f}, {o:.2f}, {h:.2f}, {l:.2f}, {c:.2f}, {c:.2f},"
        f" {c:.2f}, {volume}, {turnover_lacs:.2f}, {max(volume // 50, 1)}, {deliv_qty}, {deliv_per}"
    )


def write_cm_full(path, lines):
    path.write_text(CM_FULL_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def udiff_line(day, segment, instrument_type, symbol, *, series="", expiry=None, strike="", option="",
               o=0.0, h=0.0, l=0.0, c=0.0, prev=0.0, underlying="", settle=None, oi="", oi_change="",
               volume=0, value=0.0, isin=""):
    expiry_text = expiry.isoformat() if expiry else ""
    settle = c if settle is None else settle
    return ",".join(str(cell) for cell in (
        day.isoformat(), day.isoformat(), segment, "NSE", instrument_type, "1", isin, symbol, series,
        expiry_text, expiry_text, strike, option, symbol, o, h, l, c, c, prev, underlying, settle,
        oi, oi_change, volume, value, 10, "F1", 1, "", "", "", "", "",
    ))


def write_udiff(path, lines):
    path.write_text(UDIFF_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def index_line(name, day, o, h, l, c):
    return f"{name},{day.day:02d}-{day.month:02d}-{day.year},{o:.2f},{h:.2f},{l:.2f},{c:.2f},0,0,0,0,20,3,1.2"


def write_index(path, lines):
    path.write_text(INDEX_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def deal_line(day, symbol, client, side, quantity, price):
    return f'{nse_date(day).upper()},{symbol},{symbol} LTD,{client},{side},"{quantity:,}",{price:.2f},-'


def write_deals(path, lines):
    path.write_text(DEALS_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def write_ban(path, day, symbols):
    body = "\n".join(f"{index},{symbol}" for index, symbol in enumerate(symbols, 1))
    path.write_text(f"Securities in Ban For Trade Date {nse_date(day).upper()}:\n{body}\n", encoding="utf-8")


def make_series(bars, symbol="TEST", start=date(2025, 1, 1)):
    """Build a PriceSeries from (open, high, low, close, volume, delivery_pct) tuples."""
    from stockex.market.queries import PriceSeries

    series = PriceSeries(symbol)
    previous = None
    for day, (o, h, l, c, v, d) in zip(weekdays(start, len(bars)), bars):
        series.append({
            "trade_date": day.isoformat(), "open": o, "high": h, "low": l, "close": c,
            "prev_close": previous, "volume": v, "traded_value": c * v,
            "delivery_qty": None if d is None else int(v * d / 100), "delivery_pct": d, "series": "EQ",
        })
        previous = c
    return series


def trend_bars(start_price, count, daily_return=0.0, *, range_pct=0.02, volume=1_000_000, delivery=40.0,
               wiggle=0.0):
    """Smooth trend bars; ``wiggle`` adds a deterministic zig-zag."""
    bars, price = [], start_price
    for index in range(count):
        close = price * (1 + daily_return) * (1 + (wiggle if index % 2 else -wiggle))
        high, low = max(price, close) * (1 + range_pct / 2), min(price, close) * (1 - range_pct / 2)
        bars.append((price, high, low, close, volume, delivery))
        price = close
    return bars


def benchmark_for(series, daily_return=0.0, start=20000.0):
    closes, value = {}, start
    for day in series.dates:
        closes[day] = value
        value *= 1 + daily_return
    return closes


def generate_market(root, *, symbols=30, days=300, fo_symbols=10, seed=7, start=date(2025, 6, 2)):
    """Write a deterministic synthetic market as daily NSE files; return the file paths.

    Prices follow seeded random walks with per-symbol drift, occasional volume
    and delivery spikes, and futures open interest that moves with price, so
    every setup family has a chance to fire.
    """
    import math
    import random

    rng = random.Random(seed)
    names = [f"SYM{index:02d}" for index in range(symbols)]
    drift = {name: rng.uniform(-0.0006, 0.0018) for name in names}
    vol = {name: rng.uniform(0.012, 0.028) for name in names}
    price = {name: rng.uniform(80, 1500) for name in names}
    base_volume = {name: rng.randint(400_000, 3_000_000) for name in names}
    oi = {name: rng.randint(2_000_000, 8_000_000) for name in names[:fo_symbols]}
    nifty, vix = 22000.0, 14.0
    files = []
    for day in weekdays(start, days):
        cm_lines, fo_lines, moves = [], [], []
        expiry = _last_thursday(day)
        next_expiry = _last_thursday(date(day.year + (day.month == 12), day.month % 12 + 1, 1))
        for name in names:
            shock = rng.gauss(drift[name], vol[name])
            spike = rng.random() < 0.03
            if spike:
                shock += rng.uniform(0.02, 0.07)
            previous = price[name]
            close = max(5.0, previous * math.exp(shock))
            gap = rng.gauss(0, vol[name] / 3) + (shock / 2 if spike else 0)
            open_ = max(5.0, previous * math.exp(gap))
            high = max(open_, close) * (1 + abs(rng.gauss(0, vol[name] / 2)))
            low = min(open_, close) * (1 - abs(rng.gauss(0, vol[name] / 2)))
            volume = int(base_volume[name] * math.exp(rng.gauss(0, 0.3)) * (rng.uniform(2.5, 5) if spike else 1))
            delivery = min(95.0, max(5.0, rng.gauss(40, 8) + (15 if spike else 0)))
            cm_lines.append(cm_full_line(name, day, open_, high, low, close, previous, volume, deliv_pct=delivery))
            price[name] = close
            moves.append(close / previous - 1)
            if name in oi:
                oi[name] = max(100_000, int(oi[name] * (1 + 1.5 * (close / previous - 1) * rng.choice((1, -1))
                                                        + rng.gauss(0, 0.02))))
                for months, expiry_day in ((0, expiry), (1, next_expiry)):
                    share = 0.8 if months == 0 else 0.2
                    fo_lines.append(udiff_line(
                        day, "FO", "STF", name, expiry=expiry_day, o=open_, h=high, l=low, c=close * (1.002 + months * 0.004),
                        prev=previous, underlying=close, oi=int(oi[name] * share), volume=volume // 100,
                    ))
        nifty *= 1 + sum(moves) / len(moves)
        vix = max(9.0, vix * math.exp(rng.gauss(0, 0.04)))
        cm = root / f"sec_bhavdata_full_{day:%d%m%Y}.csv"
        write_cm_full(cm, cm_lines)
        index = root / f"ind_close_all_{day:%d%m%Y}.csv"
        write_index(index, [index_line("Nifty 50", day, nifty, nifty * 1.004, nifty * 0.996, nifty),
                            index_line("India VIX", day, vix, vix, vix, vix)])
        files += [cm, index]
        if fo_lines:
            fo = root / f"BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv"
            write_udiff(fo, fo_lines)
            files.append(fo)
    return files


def _last_thursday(day: date) -> date:
    following = date(day.year + (day.month == 12), day.month % 12 + 1, 1)
    last = following - timedelta(days=1)
    while last.weekday() != 3:
        last -= timedelta(days=1)
    return last if last >= day else _last_thursday(following)


CORP_ACTIONS_HEADER = ('"SYMBOL","COMPANY NAME","SERIES","PURPOSE","FACE VALUE","EX-DATE","RECORD DATE",'
                       '"BOOK CLOSURE START DATE","BOOK CLOSURE END DATE"')


def write_corp_actions(path, rows):
    """rows: (symbol, purpose, ex_date)"""
    lines = [f'"{s}","{s} LTD","EQ","{purpose}","10","{nse_date(ex)}","-","-","-"' for s, purpose, ex in rows]
    path.write_text(CORP_ACTIONS_HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def write_index_members(path, rows):
    """rows: (symbol, industry)"""
    lines = [f"{s} Ltd.,{industry},{s},EQ,INE{index:09d}" for index, (s, industry) in enumerate(rows)]
    path.write_text("Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(lines) + "\n", encoding="utf-8")


def write_announcements(path, rows):
    """rows: (symbol, subject, day, 'HH:MM:SS')"""
    header = '"SYMBOL","COMPANY NAME","SUBJECT","DETAILS","BROADCAST DATE/TIME","RECEIPT","DISSEMINATION"'
    lines = [f'"{s}","{s} LTD","{subject}","{subject} details","{nse_date(day)} {clock}","-","-"'
             for s, subject, day, clock in rows]
    path.write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
