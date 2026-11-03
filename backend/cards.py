"""Rich cards for the two pushed items the brief asks to be presented well.

results           — read the actual results filing, pull the headline lines for this quarter, last quarter and the
                    same quarter last year; compute EBITDA, QoQ and YoY in Python; cross-check against Screener;
                    then attach the Promise check from the ledger.
management_change — who is the person? Web search (Tavily) for their background, condensed by the cheap model,
                    with sources. Push-side enrichment, so outside sources are allowed here.
"""
import json
import re
from datetime import datetime

import httpx

from . import llm
from .config import TAVILY_API_KEY
from .db import connect, dumps
from .docs import pages
from .financials import quarterly_actuals

# ---------------------------------------------------------------- results

RESULTS_SYSTEM = """You read an Indian listed company's quarterly results statement (text extracted from a PDF; columns
may be scrambled: row labels appear first, then the numbers in the same row order, column by column).
Return Rs crore figures for exactly three columns: the latest quarter, the immediately preceding quarter, and the same
quarter a year ago. Ignore half-year / nine-month / full-year columns. Convert lakhs to crore if the statement is in
lakhs (divide by 100). Use null when a line genuinely isn't present. Negative numbers appear in brackets."""

_COL = {"type": "object", "properties": {
    "label": {"type": "string", "description": "column date, e.g. 30.09.2026"},
    "revenue_from_operations": {"type": "number", "nullable": True},
    "other_income": {"type": "number", "nullable": True},
    "finance_costs": {"type": "number", "nullable": True},
    "depreciation": {"type": "number", "nullable": True},
    "profit_before_exceptional_and_tax": {"type": "number", "nullable": True},
    "pbt": {"type": "number", "nullable": True},
    "pat": {"type": "number", "nullable": True, "description": "profit for the period (before minority interest)"},
    "operating_profit_before_provisions": {"type": "number", "nullable": True, "description": "banks/NBFCs only"},
}, "required": ["label", "revenue_from_operations", "pbt", "pat"]}

RESULTS_SCHEMA = {"type": "object", "properties": {
    "basis": {"type": "string", "enum": ["consolidated", "standalone"]},
    "units": {"type": "string", "description": "crore or lakhs as stated"},
    "current": _COL, "previous_quarter": _COL, "year_ago_quarter": _COL,
}, "required": ["basis", "current", "previous_quarter", "year_ago_quarter"]}

_STATEMENT = re.compile(r"profit\s*(\(loss\)\s*)?(from ordinary activities\s*)?before\s*(exceptional items and\s*)?tax", re.I)
_INCOME = re.compile(r"revenue from operations|total income|interest earned", re.I)


_CLEAN_TOKEN = re.compile(r"^([A-Za-z][a-z]{2,}[,.:]?|\(?[\d,]+(\.\d+)?\)?|[A-Z]{2,})$")
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()


def _quality(text: str) -> float:
    """Share of tokens that look like words or numbers. Scanned pages come out as noise and score low."""
    toks = text.split()
    return sum(1 for t in toks if _CLEAN_TOKEN.match(t)) / len(toks) if toks else 0


def _statement_pages(pgs: list[str], prefer_consolidated: bool) -> list[tuple[int, str]]:
    """Chunking by structure: of a 20-200 page filing, only the pages that look like the P&L statement,
    best guess first (wanted basis, then cleanest text). The caller tries them one at a time."""
    cands = [(i, p) for i, p in enumerate(pgs, 1) if _STATEMENT.search(p) and _INCOME.search(p)
             and not re.search(r"segment (revenue|information|reporting)|cash flows", p, re.I)]
    is_cons = lambda p: bool(re.search(r"consolidated|and subsidiaries", p[:1500], re.I))
    return sorted(cands, key=lambda c: (is_cons(c[1]) != prefer_consolidated, -_quality(c[1])))


def _period(label: str) -> str | None:
    """'30.09.2026' / 'September 30, 2026' / '30-Sep-26' -> 'Sep 2026' (Screener's column label)."""
    s = (label or "").lower()
    m = re.search(r"\d{1,2}\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{_MONTHS[int(m.group(1)) - 1].title()} {m.group(2)}"
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,.-]+(?:\d{1,2}[\s,]+)?(\d{2,4})", s)
    if m:
        yr = m.group(2) if len(m.group(2)) == 4 else "20" + m.group(2)
        return f"{m.group(1).title()} {yr}"
    return None


def _ebitda(col: dict, lender: bool):
    if "_ebitda" in col:  # column taken straight from Screener's table
        return col["_ebitda"]
    if lender:
        return col.get("operating_profit_before_provisions")
    pbe = col.get("profit_before_exceptional_and_tax") or col.get("pbt")
    parts = [pbe, col.get("finance_costs"), col.get("depreciation"), col.get("other_income")]
    if any(v is None for v in parts):
        return None
    return round(pbe + parts[1] + parts[2] - parts[3], 2)


def _chg(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100 if b > 0 else (a - b) / abs(b) * 100, 1)


_NUM_KEYS = [k for k in _COL["properties"] if k != "label"]
_IS_RESULTS = re.compile(r"(financial results?|results) (for|of) the (quarter|period|half)|approved .*financial results|"
                         r"submitted .*financial results", re.I)


def _scaled(col: dict, s: float) -> dict:
    return {k: (round(v * s, 2) if k in _NUM_KEYS and isinstance(v, (int, float)) else v) for k, v in (col or {}).items()}


def _reconcile(cur: dict, ref: dict | None) -> tuple[float, dict] | None:
    """Screener's table is built from these same filings, so the right page agrees to within rounding — once
    units line up. Statements come in Rs crore, lakh or million; find the scale that reconciles, if any.
    Revenue first; PAT as the fallback key, since banks and excise-paying companies define revenue differently."""
    if not ref:
        return None
    for ours, theirs in (("revenue_from_operations", "revenue"), ("pat", "pat")):
        v, r = cur.get(ours), ref.get(theirs)
        if v is None or not r:
            continue
        for s in (1, 0.1, 0.01, 10):  # crore, million, lakh, (mis-scaled) billion
            diff = abs(v * s - r) / abs(r) * 100
            if diff < 1:
                return s, {"fq": ref["fq"], "on": theirs, "screener_revenue": ref.get("revenue"),
                           "diff_pct": round(diff, 1), "ok": True}
    return None


def results_card(filing: dict) -> dict | None:
    from .docs import quarter_for_call
    with connect() as c:
        co = c.execute("SELECT consolidated FROM companies WHERE symbol=?", (filing["symbol"],)).fetchone()
    act = quarterly_actuals(filing["symbol"])
    lender = act["lender"]
    by_period = {q["period"]: q for q in act["quarters"]}
    # the quarter this filing should be about, from its date (results come out 2-8 weeks after quarter end)
    fd = quarter_for_call(datetime.fromisoformat(filing["ts"]).date())
    expected = by_period.get(f"{_MONTHS[fd.month - 1].title()} {fd.year}")

    try:
        pgs = pages(filing["url"])
    except Exception:
        pgs = []
    out, first, check, page_no = None, None, None, None
    for pn, text in _statement_pages(pgs, bool(co and co["consolidated"]))[:4]:
        got = llm.generate("cheap", text, purpose="results_extract", schema=RESULTS_SCHEMA, system=RESULTS_SYSTEM)
        cur = got.get("current") or {}
        rev = cur.get("revenue_from_operations")
        if rev is None or cur.get("pat") is None:
            continue
        first = first or (pn, got)
        rec = _reconcile(cur, by_period.get(_period(cur.get("label"))) or expected)
        if rec:
            s, check = rec
            out, page_no = {k: (_scaled(v, s) if isinstance(v, dict) else v) for k, v in got.items()}, pn
            break

    is_results = bool(_IS_RESULTS.search(filing.get("text") or ""))
    if out is None and first and not (expected and is_results):
        # Nothing reconciled and no reference to fall back on: show it, clearly marked unverified.
        page_no, out = first
        check = {"fq": expected["fq"] if expected else None, "ok": False,
                 "screener_revenue": expected["revenue"] if expected else None}
    if out is None:
        # Scanned PDF, no statement page, or numbers that wouldn't reconcile: use the standardised numbers for
        # that quarter instead of showing a misread — but only for a filing that *is* the results, never for a
        # notice or business update that precedes them.
        if not expected or not is_results:
            return None
        i = act["quarters"].index(expected)
        q = act["quarters"]
        to_col = lambda r: {"revenue_from_operations": r["revenue"], "pbt": r["pbt"], "pat": r["pat"], "_ebitda": r["ebitda"]}
        out = {"basis": act["label"], "current": to_col(expected) | {"label": expected["period"]},
               "previous_quarter": to_col(q[i - 1]) if i >= 1 else {}, "year_ago_quarter": to_col(q[i - 4]) if i >= 4 else {}}
        check = {"fq": expected["fq"], "ok": True, "source": "screener", "screener_revenue": expected["revenue"],
                 "note": "Couldn't read the filing reliably" if first else "Filing is a scanned image"}

    cols = [out["current"], out["previous_quarter"] or {}, out["year_ago_quarter"] or {}]
    # Some statements (e.g. IFRS-style pages) only print YoY columns. If the current column reconciled with
    # Screener, fill a missing comparison column from Screener's adjacent quarters and say so.
    qs = act["quarters"]
    idx = next((i for i, q in enumerate(qs) if check and check["ok"] and q["fq"] == check["fq"]), None)
    ref_cols = [qs[idx] if idx is not None else None, qs[idx - 1] if idx and idx >= 1 else None,
                qs[idx - 4] if idx is not None and idx >= 4 else None]
    # Reconciled on profit but not revenue = the filing defines revenue differently (gross of excise, interest
    # income for banks). Revenue-based lines would then mislead, so take those from the consistent series.
    swap_revenue = bool(check and check.get("on") == "pat" and ref_cols[0])
    lines = []
    for key, sk, label in (("revenue_from_operations", "revenue", "Revenue"),
                           ("ebitda", "ebitda", "Pre-provision profit" if lender else "EBITDA"),
                           ("pbt", "pbt", "PBT"), ("pat", "pat", "PAT")):
        if swap_revenue and sk in ("revenue", "ebitda"):
            vals = [r.get(sk) if r else None for r in ref_cols]
            lines.append({"label": label, "now": vals[0], "qoq": _chg(vals[0], vals[1]), "yoy": _chg(vals[0], vals[2]),
                          "prev": vals[1], "year_ago": vals[2], "filled_from_screener": ["now", "qoq", "yoy"]})
            continue
        vals = [_ebitda(c_, lender) if key == "ebitda" else c_.get(key) for c_ in cols]
        filled = []
        for j in (1, 2):
            if vals[j] is None and ref_cols[j] and ref_cols[j].get(sk) is not None:
                vals[j] = ref_cols[j][sk]
                filled.append("qoq" if j == 1 else "yoy")
        lines.append({"label": label, "now": vals[0], "qoq": _chg(vals[0], vals[1]), "yoy": _chg(vals[0], vals[2]),
                      "prev": vals[1], "year_ago": vals[2], "filled_from_screener": filled})
    rev = lines[0]["now"]
    margin = round(lines[1]["now"] / rev * 100, 1) if rev and lines[1]["now"] is not None else None

    return {"kind": "results", "basis": out.get("basis"), "quarter": out["current"].get("label"),
            "lines": lines, "margin": margin, "lender": lender,
            "source": {"url": filing["url"], "page": page_no}, "check": check,
            "verified": bool(check and check.get("ok")),
            "promises": promise_check(filing["symbol"])}


def promise_check(symbol: str) -> list[dict]:
    """The ledger's threads on headline numbers, newest-relevant first: what was promised, what came."""
    with connect() as c:
        row = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    if not row:
        return []
    L = json.loads(row["data"])
    if L.get("status") != "ok":
        return []
    pri = {"ebitda_margin": 0, "revenue_growth": 1, "volume_growth": 2, "pat_growth": 3, "capex": 4, "other": 5}
    threads = sorted(L["threads"], key=lambda t: (pri.get(t["metric"], 9), t["verdict"] == "pending"))
    return [{"topic": t["topic"], "verdict": t["verdict"], "line": t["verdict_line"]} for t in threads[:3]]


# ---------------------------------------------------------------- management change

BIO_SYSTEM = """Write a two-sentence professional background of the named person from the search results: their
previous roles and companies with years where given, and education only if stated. Facts only, no praise.
If the results are about a different person or say nothing useful, return found=false."""
BIO_SCHEMA = {"type": "object", "properties": {
    "found": {"type": "boolean"}, "bio": {"type": "string"},
    "previous": {"type": "string", "description": "most recent prior role and company, max 8 words"},
    "source_indexes": {"type": "array", "items": {"type": "integer"}},
}, "required": ["found", "bio", "previous", "source_indexes"]}


def _tavily(query: str) -> list[dict]:
    if not TAVILY_API_KEY:
        return []
    r = httpx.post("https://api.tavily.com/search", timeout=30,
                   headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
                   json={"query": query, "max_results": 5, "search_depth": "basic"})
    r.raise_for_status()
    return r.json().get("results", [])


def management_card(filing: dict, detail: dict, company: str) -> dict | None:
    person = (detail.get("person") or "").strip()
    if not person:
        return None
    role = detail.get("role") or ""
    card = {"kind": "management_change", "person": person, "role": role, "direction": detail.get("direction")}
    if detail.get("direction") == "leaving":
        return card  # the brief asks for the incoming person's background; for exits the facts are enough
    hits = _tavily(f"{person} {role} {company} career background LinkedIn")
    if not hits:
        return card
    ctx = "\n\n".join(f"[{i}] {h['title']} — {h['url']}\n{(h.get('content') or '')[:700]}" for i, h in enumerate(hits))
    out = llm.generate("cheap", f"Person: {person}, appointed {role} at {company}.\n\n{ctx}",
                       purpose="bio", schema=BIO_SCHEMA, system=BIO_SYSTEM)
    if out.get("found"):
        card |= {"bio": out["bio"], "previous": out.get("previous"),
                 "sources": [{"title": hits[i]["title"], "url": hits[i]["url"]}
                             for i in out.get("source_indexes", []) if 0 <= i < len(hits)][:3]}
    return card


# ---------------------------------------------------------------- orchestration

def enrich(symbols: list[str] | None = None, since: str | None = None) -> int:
    """Build cards for high-materiality results and leadership filings that don't have one yet."""
    q = """SELECT f.*, c.name FROM filings f JOIN companies c USING(symbol)
           WHERE f.category IN ('results','management_change') AND f.detail IS NOT NULL"""
    args = []
    if since:
        q += " AND f.ts >= ?"
        args.append(since)
    if symbols:
        q += f" AND f.symbol IN ({','.join('?' * len(symbols))})"
        args += symbols
    with connect() as c:
        rows = [dict(r) for r in c.execute(q + " ORDER BY f.ts DESC", args)]
    n = 0
    for f in rows:
        d = json.loads(f["detail"])
        if d.get("materiality") != "high" or "card" in d:
            continue
        try:
            if f["category"] == "results" and f["url"]:
                card = results_card(f)
            elif f["category"] == "management_change":
                card = management_card(f, d, f["name"])
            else:
                card = None
        except Exception as e:
            card = {"kind": "error", "error": f"{type(e).__name__}: {str(e)[:120]}"}
        d["card"] = card
        with connect() as c:
            c.execute("UPDATE filings SET detail=? WHERE id=?", (dumps(d), f["id"]))
        n += 1
    return n
