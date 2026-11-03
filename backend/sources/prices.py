"""End-of-day price and volume from Yahoo's public chart endpoint (what yfinance wraps)."""
from datetime import datetime, timedelta, timezone

from ..db import connect
from .http import get

IST = timezone(timedelta(hours=5, minutes=30))


INDEX = {"NIFTY": "^NSEI"}  # benchmark, so a stock's move can be judged against the market's


def fetch_prices(symbol: str, range_: str = "1y") -> list[tuple]:
    ticker = INDEX.get(symbol, f"{symbol}.NS")
    r = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            params={"range": range_, "interval": "1d"})
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(res.get("timestamp") or []):
        if q["close"][i] is None:
            continue  # holidays / partial rows
        day = datetime.fromtimestamp(ts, IST).date().isoformat()
        rows.append((symbol, day, q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0))
    return rows


def ingest_prices(symbol: str) -> int:
    rows = fetch_prices(symbol)
    with connect() as c:
        c.executemany("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)
