"""Corporate announcements from NSE's public JSON feed."""
from datetime import date, datetime, timedelta

from ..db import connect
from .http import get

NSE_API = "https://www.nseindia.com/api/corporate-announcements"


def fetch_filings(symbol: str, since: date, until: date | None = None) -> list[dict]:
    until = until or date.today()
    r = get(NSE_API,
            params={"index": "equities", "symbol": symbol,
                    "from_date": since.strftime("%d-%m-%Y"), "to_date": until.strftime("%d-%m-%Y")},
            referer="https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            accept="application/json")
    r.raise_for_status()
    return r.json() if isinstance(r.json(), list) else []


def ingest_filings(symbol: str, days: int = 120) -> int:
    items = fetch_filings(symbol, date.today() - timedelta(days=days))
    rows = []
    for a in items:
        ts = datetime.strptime(a["sort_date"], "%Y-%m-%d %H:%M:%S").isoformat()
        rows.append((a["seq_id"], symbol, ts, (a.get("desc") or "").strip(),
                     (a.get("attchmntText") or "").strip(), a.get("attchmntFile"), a.get("fileSize")))
    with connect() as c:
        # Keep any classification already done; only refresh the raw fields.
        c.executemany("""
            INSERT INTO filings (id, symbol, ts, nse_desc, text, url, size) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET nse_desc=excluded.nse_desc, text=excluded.text,
                                          url=excluded.url, size=excluded.size""", rows)
    return len(rows)
