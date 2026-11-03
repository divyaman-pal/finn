"""The Promise Ledger: what management said they'd deliver, against what they delivered.

1. cheap model, per call, per chunk  -> claims (forward-looking promises + reported outcomes), each with
                                        a verbatim quote and page number
2. Python                             -> the actuals table from reported quarterly numbers
3. strong model, once per company     -> threads claims about the same thing across quarters, gives verdicts,
                                        writes a bull and bear case citing claim ids
4. Python                             -> re-checks numeric verdicts against reported numbers (numbers beat
                                        narrative), verifies every quote exists in the source on that page
"""
import json
import re
from datetime import date, datetime, timezone

from . import llm
from .db import connect, dumps
from .docs import fy_label, nse_transcript, pages, pick_calls, stated_quarter
from .financials import quarterly_actuals

CHUNK_WORDS = 3500
METRICS = ["revenue_growth", "ebitda_margin", "pat_growth", "volume_growth", "capex", "other"]

# ---------------------------------------------------------------- 1. extraction (cheap tier)

EXTRACT_SYSTEM = """You read Indian listed-company earnings-call transcripts and investor presentations.
Extract only concrete, checkable statements by management (not analysts), of two kinds:
- "forward": guidance or a promise about a future period — growth, margin, capex, capacity, launches,
  market share, debt, timelines. Must be specific enough that someone could later say if it came true.
- "reported": what management says was actually achieved this period on a metric they had guided on
  (e.g. "volume grew 9%", "margin came in at 18.2%").
Skip pleasantries, strategy slogans, vague optimism ("we remain confident"), and anything said by an analyst
or participant — including analysts restating management's numbers ("you are saying..."). The quote must be
management's own words.
quote must be copied verbatim from the text (max 40 words). page is the [p N] marker the quote sits under.
target_low/target_high: numbers only when management gives them (a single number -> both equal).
basis for growth: "reported" (rupee revenue), "constant_currency", "volume", or "other"."""

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["forward", "reported"]},
            "topic": {"type": "string", "description": "2-4 word label, e.g. 'decorative volume growth'"},
            "metric": {"type": "string", "enum": METRICS},
            "statement": {"type": "string", "description": "plain-English paraphrase, max 20 words"},
            "quote": {"type": "string"},
            "page": {"type": "integer"},
            "target_low": {"type": "number", "nullable": True},
            "target_high": {"type": "number", "nullable": True},
            "unit": {"type": "string", "description": "%, Cr, bps, x, units, or empty"},
            "basis": {"type": "string", "enum": ["reported", "constant_currency", "volume", "other"]},
            "horizon": {"type": "string", "description": "period the promise is for, e.g. 'FY27', 'next quarter', 'H2 FY26', 'medium term'"},
            "speaker": {"type": "string"},
        },
        "required": ["kind", "topic", "metric", "statement", "quote", "page", "basis", "horizon"],
    }}},
    "required": ["claims"],
}

_BOILERPLATE = re.compile(r"(?im)^.*(disclaimer|this is a memorandum|forward-looking statements|"
                          r"ladies and gentlemen, good day|operator:).*$")


def _chunks(pgs: list[str]) -> list[str]:
    out, buf, words = [], [], 0
    for i, t in enumerate(pgs, 1):
        t = _BOILERPLATE.sub("", t)
        n = len(t.split())
        if buf and words + n > CHUNK_WORDS:
            out.append("\n".join(buf)); buf, words = [], 0
        buf.append(f"[p {i}]\n{t}"); words += n
    if buf:
        out.append("\n".join(buf))
    return out


def extract_claims(symbol: str, call: dict) -> list[dict]:
    pgs = pages(call["url"])
    q = stated_quarter(pgs[:3])
    if q:  # the document knows its own quarter better than the listing date does
        call["quarter"], call["fq"] = q.isoformat(), fy_label(q)
    claims = []
    for chunk in _chunks(pgs):
        prompt = f"Company: {symbol}. Call for {call['fq']} (quarter ending {call['quarter'][:7]}).\n\n{chunk}"
        out = llm.generate("cheap", prompt, purpose="extract_claims", schema=CLAIM_SCHEMA, system=EXTRACT_SYSTEM)
        claims.extend(out.get("claims", []))
    for c in claims:
        c["fq"], c["quarter"], c["source_url"], c["source_kind"] = call["fq"], call["quarter"], call["url"], call["kind"]
    return claims


# ---------------------------------------------------------------- 4a. receipts

# The cheap extractor sometimes keeps an analyst restating guidance back to management. Catch it deterministically.
_ANALYST_VOICE = re.compile(r"\b(you('re| are| were)\s+(guiding|saying|expecting|talking|suggesting|indicating)|"
                            r"you (said|mentioned|guided|indicated)|your (guidance|target|earlier))\b", re.I)

def _norm(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9%.]+", " ", s.lower()).split()


def verify_quote(quote: str, pgs: list[str], page: int) -> int | None:
    """Return the page the quote is really on (checking ±1 page), or None if it isn't in the source."""
    q = _norm(quote)
    if len(q) < 4:
        return None
    grams = {tuple(q[i:i + 4]) for i in range(len(q) - 3)}
    best, best_page = 0.0, None
    for p in (page, page - 1, page + 1, *range(1, len(pgs) + 1)):
        if not 1 <= p <= len(pgs):
            continue
        w = _norm(pgs[p - 1])
        have = {tuple(w[i:i + 4]) for i in range(len(w) - 3)}
        score = len(grams & have) / len(grams)
        if score > best:
            best, best_page = score, p
        if best >= 0.8:
            break
    return best_page if best >= 0.6 else None


# ---------------------------------------------------------------- 3. threading (strong tier)

THREAD_SYSTEM = """You are a sceptical buy-side analyst auditing management credibility.
You get claims extracted from a company's last four earnings calls (oldest first), each with an id, and
the company's reported quarterly numbers. Build the Promise Ledger:
- Group forward claims about the same thing across calls into one thread. Follow it forward in time.
- Verdict per thread:
  delivered  — later reported numbers or management's own later statements show it was met
  missed     — the period passed and it was not met (say by how much)
  moved      — management later revised the target or pushed the timeline, ideally without saying so plainly
  dropped    — never mentioned again in later calls although its period has arrived or it was a headline theme
  pending    — its period hasn't ended yet and nothing contradicts it
- Use the reported numbers table where it applies; it outranks management's narrative.
- Prefer 5-8 threads that matter to an investor over many trivial ones. Skip threads with only one vague claim.
- verdict_line: one sentence with the numbers, e.g. "Guided 8-10% volume growth for FY26; delivered 4.1%."
Then give the 3 strongest bull and 3 strongest bear points, each grounded ONLY in these claims and numbers
(cite ids). No outside knowledge, no news, no valuation opinions. Be terse and specific."""

THREAD_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "one line: how credible management's guidance has been"},
        "threads": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "metric": {"type": "string", "enum": METRICS},
                "verdict": {"type": "string", "enum": ["delivered", "missed", "moved", "dropped", "pending"]},
                "verdict_line": {"type": "string"},
                "promise_ids": {"type": "array", "items": {"type": "string"}},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic", "metric", "verdict", "verdict_line", "promise_ids", "evidence_ids"],
        }},
        "bull": {"type": "array", "items": {"type": "object", "properties": {
            "point": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["point", "ids"]}},
        "bear": {"type": "array", "items": {"type": "object", "properties": {
            "point": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["point", "ids"]}},
    },
    "required": ["headline", "threads", "bull", "bear"],
}


def _claims_brief(claims: list[dict]) -> str:
    lines = []
    for c in claims:
        tgt = ""
        if c.get("target_low") is not None:
            lo, hi = c["target_low"], c.get("target_high", c["target_low"])
            tgt = f" target={lo}{'' if hi in (None, lo) else f'-{hi}'}{c.get('unit') or ''}"
        lines.append(f"{c['id']} [{c['fq']}] {c['kind']} | {c['topic']} | {c['metric']}/{c['basis']} | "
                     f"horizon={c['horizon']}{tgt} | {c['statement']}")
    return "\n".join(lines)


def _actuals_brief(act: dict) -> str:
    cols = ["fq", "revenue", "revenue_yoy", "ebitda_margin", "pat", "pat_yoy"]
    rows = [" | ".join(cols)]
    for r in act["quarters"][-6:]:
        rows.append(" | ".join("" if r.get(k) is None else str(r[k]) for k in cols))
    return f"Reported quarterly numbers (Rs Cr, %; {act['label']}):\n" + "\n".join(rows)


# ---------------------------------------------------------------- 4b. numbers beat narrative

def _numeric_check(thread: dict, claims: dict, act: dict) -> dict | None:
    """For margin and rupee-growth promises aimed at a specific quarter we have, compute the answer ourselves."""
    if thread["metric"] not in ("ebitda_margin", "revenue_growth", "pat_growth"):
        return None
    key = {"ebitda_margin": "ebitda_margin", "revenue_growth": "revenue_yoy", "pat_growth": "pat_yoy"}[thread["metric"]]
    by_fq = {r["fq"]: r for r in act["quarters"]}
    for pid in thread["promise_ids"]:
        c = claims.get(pid)
        if not c or c.get("target_low") is None or c.get("basis") not in ("reported", "other"):
            continue
        if thread["metric"] == "revenue_growth" and c["basis"] != "reported":
            continue
        hz = (c.get("horizon") or "").upper().replace(" ", "")
        target_fq = None
        if "NEXTQUARTER" in hz:
            i = [r["fq"] for r in act["quarters"]].index(c["fq"]) if c["fq"] in by_fq else None
            if i is not None and i + 1 < len(act["quarters"]):
                target_fq = act["quarters"][i + 1]["fq"]
        else:
            m = re.search(r"Q([1-4])FY(\d{2})", hz)
            if m:
                target_fq = f"Q{m.group(1)} FY{m.group(2)}"
        if not target_fq or target_fq not in by_fq or by_fq[target_fq].get(key) is None:
            continue
        actual = by_fq[target_fq][key]
        lo = c["target_low"]
        return {"claim": pid, "quarter": target_fq, "target": lo, "actual": actual,
                "met": actual >= lo, "source": f"reported {act['label']} numbers"}
    return None


_BEAT = re.compile(r"favou?rable miss|\bbeat\b|\bbeaten\b|exceed|ahead of (guidance|target)|outperform", re.I)


def normalise_verdicts(ledger: dict) -> dict:
    """A target overshot in the investor's favour is a promise kept, not a miss."""
    for t in ledger.get("threads", []):
        if t["verdict"] == "missed" and _BEAT.search(t.get("verdict_line", "")):
            t["verdict"], t["beat"] = "delivered", True
    return ledger


# ---------------------------------------------------------------- orchestration

def build_ledger(symbol: str, force: bool = False) -> dict:
    with connect() as c:
        row = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    if row and not force:
        return json.loads(row["data"])

    kind, calls = pick_calls(symbol)
    if not calls:
        return {"symbol": symbol, "status": "no_sources",
                "note": "No earnings-call transcripts or investor presentations are available for this company."}

    claims, page_text = [], {}
    for call in calls:
        try:
            try:
                pages(call["url"])
            except ValueError:  # dead link: fall back to the copy filed with NSE
                alt = nse_transcript(symbol, call["period"]) if call["kind"] == "transcript" else None
                if not alt:
                    raise
                call["url"] = alt
            page_text[call["url"]] = pages(call["url"])
            if sum(len(p.split()) for p in page_text[call["url"]]) < 800:
                raise ValueError("Only a cover letter is on file; the company didn't file the transcript itself")
            claims.extend(extract_claims(symbol, call))
        except Exception as e:  # one unreadable PDF shouldn't kill the ledger
            call["error"] = str(e)[:160] if isinstance(e, ValueError) else f"{type(e).__name__}: {str(e)[:120]}"

    # Receipts: keep only management's words, and only quotes that really exist in the source.
    kept = []
    for c in claims:
        if _ANALYST_VOICE.search(c["quote"]):
            continue
        p = verify_quote(c["quote"], page_text.get(c["source_url"], []), c.get("page") or 1)
        if p:
            c["page"] = p
            kept.append(c)
    dropped_unverified = len(claims) - len(kept)
    for i, c in enumerate(kept, 1):
        c["id"] = f"c{i}"
    by_id = {c["id"]: c for c in kept}

    act = quarterly_actuals(symbol)
    prompt = (f"Company: {symbol}. Sources: {kind}s for {', '.join(c['fq'] for c in calls)}.\n\n"
              f"{_actuals_brief(act)}\n\nClaims (oldest call first):\n{_claims_brief(kept)}")
    meta = {"upgrade": force}
    out = llm.generate("strong", prompt, purpose="ledger", schema=THREAD_SCHEMA, system=THREAD_SYSTEM, meta=meta)

    for t in out["threads"]:
        t["promise_ids"] = [i for i in t["promise_ids"] if i in by_id]
        t["evidence_ids"] = [i for i in t["evidence_ids"] if i in by_id]
        chk = _numeric_check(t, by_id, act)
        if chk:
            t["check"] = chk
            want = "delivered" if chk["met"] else "missed"
            if t["verdict"] in ("delivered", "missed") and t["verdict"] != want:
                t["verdict"], t["overridden"] = want, True
    out["threads"] = [t for t in out["threads"] if t["promise_ids"]]
    normalise_verdicts(out)
    for side in ("bull", "bear"):
        out[side] = [p | {"ids": [i for i in p["ids"] if i in by_id]} for p in out[side]]

    ledger = {
        "symbol": symbol, "status": "ok", "source_kind": kind,
        "calls": [{k: c[k] for k in ("fq", "period", "url", "kind") if k in c} | ({"error": c["error"]} if "error" in c else {})
                  for c in calls],
        "claims": by_id, "unverified_dropped": dropped_unverified,
        "actuals": act,
        "model": meta.get("model"), "degraded": llm.degraded(meta.get("model")),
        **out,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO fin_tables VALUES (?,?,?)", (symbol, "ledger", dumps(ledger)))
    return ledger
