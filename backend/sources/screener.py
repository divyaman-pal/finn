"""Fundamentals from screener.in: standardised financial tables plus links to primary documents
(annual reports, concall transcripts). We use Screener only for numbers and links, never its AI notes."""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..db import connect, dumps
from .http import get

SECTIONS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding"]


def _num(s: str):
    s = s.replace(",", "").replace("%", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _table(section) -> dict | None:
    tbl = section.find("table") if section else None
    if not tbl:
        return None
    periods = [th.get_text(strip=True) for th in tbl.select("thead th")][1:]
    rows = {}
    for tr in tbl.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        name = re.sub(r"\s*\+$", "", cells[0]).strip()
        if not name or name == "Raw PDF":
            continue
        rows[name] = [_num(v) for v in cells[1:]]
    return {"periods": periods, "rows": rows}


_MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _latest_quarter(soup: BeautifulSoup) -> tuple[int, int]:
    """(year, month) of the newest quarter that actually has numbers, or (0, 0)."""
    q = _table(soup.find(id="quarters"))
    if not q:
        return (0, 0)
    for i in range(len(q["periods"]) - 1, -1, -1):
        if any(vals[i] is not None for vals in q["rows"].values() if i < len(vals)):
            mon, _, yr = q["periods"][i].partition(" ")
            return (int(yr), _MONTHS.get(mon, 0)) if yr.isdigit() else (0, 0)
    return (0, 0)


def _page(symbol: str) -> tuple[BeautifulSoup, bool]:
    """Prefer consolidated numbers, unless standalone is more current (some companies stop
    reporting consolidated results, leaving a stale table behind)."""
    pages = {}
    for consolidated, path in ((True, "consolidated/"), (False, "")):
        r = get(f"https://www.screener.in/company/{symbol}/{path}")
        if r.status_code == 404:
            raise LookupError(f"{symbol} not found on Screener")
        r.raise_for_status()
        pages[consolidated] = BeautifulSoup(r.text, "lxml")
    if _latest_quarter(pages[True]) >= _latest_quarter(pages[False]) > (0, 0):
        return pages[True], True
    return pages[False], False


def ingest_screener(symbol: str, weight: float | None = None) -> dict:
    soup, consolidated = _page(symbol)

    name = soup.select_one("h1")
    about = soup.select_one(".company-profile .about")
    ratios = {}
    for li in soup.select("#top-ratios li"):
        n, v = li.select_one(".name"), li.select_one(".value")
        if n and v:
            ratios[n.get_text(strip=True)] = " ".join(v.get_text(" ", strip=True).split())
    peers = [a.get_text(strip=True) for a in soup.select('#peers a[href*="/market/"]')]
    bse = re.search(r"/(\d{6})/", " ".join(a["href"] for a in soup.select('a[href*="bseindia.com/stock-share-price"]')))

    docs = []
    for a in soup.select("div.annual-reports a"):
        m = re.search(r"(\d{4})", a.get_text(" ", strip=True))
        docs.append((a["href"], symbol, "annual_report", m.group(1) if m else None))
    for li in soup.select("div.concalls li"):
        period = li.find("div").get_text(strip=True)
        for a in li.select("a.button-chip"):
            label = a.get_text(strip=True).lower()
            if label in ("transcript", "ppt"):
                docs.append((a["href"], symbol, label, period))

    with connect() as c:
        c.execute("""
            INSERT INTO companies (symbol, name, sector, industry, bse_code, about, ratios, consolidated, weight, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, sector=excluded.sector, industry=excluded.industry,
                bse_code=excluded.bse_code, about=excluded.about, ratios=excluded.ratios,
                consolidated=excluded.consolidated, weight=excluded.weight, updated_at=excluded.updated_at""",
                  (symbol, name.get_text(strip=True) if name else symbol,
                   peers[0] if peers else None, peers[-1] if peers else None,
                   bse.group(1) if bse else None,
                   about.get_text(" ", strip=True) if about else None,
                   dumps(ratios), int(consolidated), weight,
                   datetime.now(timezone.utc).isoformat(timespec="seconds")))
        for sec in SECTIONS:
            t = _table(soup.find(id=sec))
            if t:
                c.execute("INSERT OR REPLACE INTO fin_tables VALUES (?,?,?)", (symbol, sec, dumps(t)))
        c.executemany("""INSERT INTO documents (url, symbol, kind, period) VALUES (?,?,?,?)
                         ON CONFLICT(url) DO NOTHING""", docs)
    return {"consolidated": consolidated, "docs": len(docs), "ratios": len(ratios)}
