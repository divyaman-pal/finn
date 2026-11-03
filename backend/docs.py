"""Primary documents: pick the right transcripts, extract their text page by page, map calls to quarters."""
import io
import json
import logging
import re
from datetime import date

from pypdf import PdfReader

from .db import connect, dumps
from .sources.http import get_file

logging.getLogger("pypdf").setLevel(logging.ERROR)  # malformed-but-readable PDFs are common on BSE

MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def parse_period(label: str) -> date | None:
    """'Oct 2026' -> date(2026, 10, 1)."""
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{4})", label or "")
    return date(int(m.group(2)), MONTHS[m.group(1)], 1) if m and m.group(1) in MONTHS else None


def quarter_for_call(call: date) -> date:
    """A call discusses the latest quarter that closed before it: Oct call -> Sep quarter."""
    y, m = call.year, call.month
    q = max((qm for qm in (3, 6, 9, 12) if qm < m), default=None)
    return date(y, q, 1) if q else date(y - 1, 12, 1)


def fy_label(q: date) -> str:
    """Indian fiscal quarters: Apr–Jun is Q1. Sep 2026 -> 'Q2 FY27'."""
    fq = {6: 1, 9: 2, 12: 3, 3: 4}[q.month]
    fy = q.year + 1 if q.month > 3 else q.year
    return f"Q{fq} FY{fy % 100:02d}"


def stated_quarter(first_pages: list[str], listed: date | None = None) -> date | None:
    """Trust the document over the listing date: read 'quarter ended 30th June 2026', 'quarter ended June 30,
    2026', 'Q1 FY2027' or 'Q1 FY2026-27'. With `listed` (the call's listing month), a reading that isn't
    0-6 months before it is rejected: a mislabelled or misread document shouldn't move a call a year."""
    head = re.sub(r"\s+", " ", " ".join(first_pages)[:6000])
    found = None
    m = re.search(r"quarter (?:and \w+ )?ended (?:on )?(?:\d{1,2}(?:st|nd|rd|th)? ([A-Z][a-z]+),? (\d{4})|"
                  r"([A-Z][a-z]+) \d{1,2},? (\d{4}))", head)
    if m:
        mon, yr = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if mon[:3] in MONTHS:
            found = date(int(yr), MONTHS[mon[:3]], 1)
    if not found:
        m = re.search(r"Q([1-4]) ?[-' ]? ?FY ?'?(\d{2,4})(?: ?[-–/] ?(\d{2,4}))?", head)
        if m:
            fq = int(m.group(1))
            yr = m.group(3) or m.group(2)  # 'FY2026-27' names the year that ends in 2027
            fy = int(yr) if len(yr) == 4 else 2000 + int(yr[-2:])
            found = date(fy - 1 if fq < 4 else fy, {1: 6, 2: 9, 3: 12, 4: 3}[fq], 1)
    if found and listed:
        months = (listed.year - found.year) * 12 + listed.month - found.month
        if not 0 <= months <= 6:
            return None
    return found


def pick_calls(symbol: str, n: int = 4) -> tuple[str, list[dict]]:
    """The last n distinct quarterly calls. Falls back to investor presentations for companies that
    don't hold earnings calls (e.g. ITC), and says which source it used."""
    with connect() as c:
        rows = c.execute("SELECT url, kind, period FROM documents WHERE symbol=? AND kind IN ('transcript','ppt')",
                         (symbol,)).fetchall()
    for kind in ("transcript", "ppt"):
        seen, picked = set(), []
        docs = sorted((r for r in rows if r["kind"] == kind and parse_period(r["period"])),
                      key=lambda r: parse_period(r["period"]), reverse=True)
        for r in docs:
            q = quarter_for_call(parse_period(r["period"]))
            if q in seen:
                continue
            seen.add(q)
            picked.append({"url": r["url"], "kind": kind, "period": r["period"],
                           "quarter": q.isoformat(), "fq": fy_label(q)})
            if len(picked) == n:
                break
        if picked:
            return kind, picked[::-1]  # oldest first: promises flow forward in time
    return "none", []


def nse_transcript(symbol: str, period: str) -> str | None:
    """Company-hosted transcript links rot. The same transcript is filed with NSE, so look it up there."""
    from datetime import timedelta
    from .sources.filings import fetch_filings
    d = parse_period(period)
    if not d:
        return None
    try:
        items = fetch_filings(symbol, d - timedelta(days=20), d + timedelta(days=50))
    except Exception:
        return None
    hits = [a for a in items if "transcript" in (a.get("attchmntText") or "").lower() and a.get("attchmntFile")]
    hits.sort(key=lambda a: a["sort_date"])
    return hits[0]["attchmntFile"] if hits else None


def pages(url: str) -> list[str]:
    """Text of each page, extracted once and stored."""
    with connect() as c:
        row = c.execute("SELECT text FROM documents WHERE url=?", (url,)).fetchone()
    if row and row["text"]:
        return json.loads(row["text"])
    data = get_file(url, referer="https://www.bseindia.com/")
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {url}")
    out = []
    for p in PdfReader(io.BytesIO(data)).pages:
        t = p.extract_text() or ""
        out.append(re.sub(r"[ \t]+", " ", t).strip())
    with connect() as c:
        c.execute("UPDATE documents SET text=? WHERE url=?", (dumps(out), url))
    return out
