"""Filing triage: decide what every exchange filing is, and how much it matters.

Three routes, cheapest first:
  1. rules     — NSE's own subject line settles routine paperwork for free (newspaper ads, certificates, ESOPs)
  2. one-liner — everything else goes to the cheap model in batches of 25, using NSE's one-line description
  3. peek      — opaque one-liners ("...informed the Exchange about General Updates") also carry the first
                 page of the attachment, because the one-liner alone says nothing
"""
import json
import re

from . import llm
from .db import connect, dumps
from .docs import pages

CATEGORIES = ["results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
              "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
              "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified"]

# NSE subject -> (category, materiality) when the subject alone is decisive and the item is routine.
ROUTINE = {
    "Copy of Newspaper Publication": ("results", "low"),
    "Certificate under SEBI (Depositories and Participants) Regulations, 2018": ("unclassified", "low"),
    "ESOP/ESOS/ESPS": ("unclassified", "low"),
    "Trading Window": ("unclassified", "low"),
    "Committee Meeting Updates": ("unclassified", "low"),
    "Address Change": ("unclassified", "low"),
    "Corrigendum": ("unclassified", "low"),
    "Monitoring Agency Report": ("fund_raise", "low"),
    "Integrated Filing- Financial": ("results", "low"),
}
_INVESTOR_MEET = "Analysts/Institutional Investor Meet/Con. Call Updates"
_OPAQUE = re.compile(r"(informed the Exchange (about|regarding) '?(general updates|updates)'?\.?$|"
                     r"Regulation 30|Reg 30|^General Updates$)", re.I)

TRIAGE_SYSTEM = """You triage Indian stock-exchange filings for a busy portfolio investor. For each filing return:
- category: one of """ + ", ".join(CATEGORIES) + """
  (results = quarterly/annual results, results decks, the board meeting approving them;
   press_release = order wins, launches, partnerships, rumour clarifications;
   unclassified = routine paperwork that doesn't move the stock)
- materiality: high (could move the stock or change the thesis: results, CEO/CFO/MD/Chairman change, acquisition,
  large fund raise, rating downgrade, regulatory penalty, big order relative to the company's size, new plant
  starting production), medium (worth a glance: rating reaffirmed, independent/non-executive director changes,
  mid-sized orders, dividends), low (routine: notices, schedules, record dates, ESOP allotments, awards, PR).
- headline: what happened, max 12 words, specific (names, amounts, dates), no company name, no hype.
- why: for high/medium only, max 18 words, and only a SPECIFIC fact from the filing that changes the picture
  (an amount, a capacity, a rating, a penalty size, who the person replaces). If the filing has no such fact,
  return "". Never write generic lines like "results drive sentiment" or "affects governance".
- person / role / direction: for management_change only (direction: joining, leaving, or redesignated).
Never invent amounts or names that aren't in the text."""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "materiality": {"type": "string", "enum": ["high", "medium", "low"]},
            "headline": {"type": "string"},
            "why": {"type": "string"},
            "person": {"type": "string", "nullable": True},
            "role": {"type": "string", "nullable": True},
            "direction": {"type": "string", "nullable": True},
        },
        "required": ["id", "category", "materiality", "headline", "why"],
    }}},
    "required": ["items"],
}

BATCH = 25


def _clean(text: str) -> str:
    """Strip NSE boilerplate so the model reads the substance."""
    t = re.sub(r"^.*?has (informed|submitted to) the Exchange (about|regarding|that)\s*", "", text or "", flags=re.I)
    return t.strip(" '.\"") or text


def _peek(url: str | None) -> str:
    if not url:
        return ""
    try:
        return " ".join(" ".join(pages(url)[:2]).split()[:350])
    except Exception:
        return ""


def triage_pending(symbols: list[str] | None = None, limit: int | None = None) -> int:
    """Classify every filing that hasn't been classified yet. Returns how many were done."""
    q = "SELECT f.id, f.symbol, f.nse_desc, f.text, f.url, c.name FROM filings f JOIN companies c USING(symbol) " \
        "WHERE f.category IS NULL"
    args = []
    if symbols:
        q += f" AND f.symbol IN ({','.join('?' * len(symbols))})"
        args += symbols
    q += " ORDER BY f.ts DESC" + (f" LIMIT {int(limit)}" if limit else "")
    with connect() as c:
        rows = [dict(r) for r in c.execute(q, args)]

    done, todo = [], []
    for r in rows:
        if r["nse_desc"] in ROUTINE:
            cat, mat = ROUTINE[r["nse_desc"]]
            done.append((cat, None, dumps({"materiality": mat, "headline": _clean(r["text"])[:120], "route": "rule"}), r["id"]))
        elif r["nse_desc"] == _INVESTOR_MEET and not re.search(r"transcript|recording|audio|conference call", r["text"], re.I):
            done.append(("investor_meetings", None, dumps({"materiality": "low", "headline": "Met institutional investors", "route": "rule"}), r["id"]))
        else:
            todo.append(r)

    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        lines = []
        for r in batch:
            text = _clean(r["text"])
            peek = _peek(r["url"]) if _OPAQUE.search(r["text"]) or len(text) < 25 else ""
            r["route"] = "peek" if peek else "one-liner"
            lines.append(f"id={r['id']} | {r['name']} | NSE subject: {r['nse_desc']} | {text}"
                         + (f"\n   attachment page 1: {peek}" if peek else ""))
        out = llm.generate("cheap", "\n".join(lines), purpose="triage", schema=TRIAGE_SCHEMA, system=TRIAGE_SYSTEM)
        by_id = {x["id"]: x for x in out.get("items", [])}
        for r in batch:
            x = by_id.get(r["id"])
            if not x:
                continue  # left NULL; picked up on the next run
            detail = {"materiality": x["materiality"], "headline": x["headline"], "why": x.get("why") or "",
                      "route": r["route"]}
            if x["category"] == "management_change":
                detail |= {k: x.get(k) for k in ("person", "role", "direction")}
            done.append((x["category"], x.get("why") or None, dumps(detail), r["id"]))

    with connect() as c:
        c.executemany("UPDATE filings SET category=?, summary=?, detail=? WHERE id=?", done)
    return len(done)
