"""Ask a company a question. Answers come only from what FINN has already read for it — the claims extracted
from its calls (each tied to a quote and page) and the numbers computed from its financials — and cite them.
No outside knowledge, no news: if the sources don't say, the answer says so."""
import json
import re

from . import llm
from .db import connect
from .financials import vitals

ASK_SYSTEM = """You answer an investor's question about one Indian listed company using ONLY the facts provided:
claims from management's own earnings calls (ids c1, c2, ...) and figures computed from reported financials
(ids n1, n2, ...). Rules:
- Answer in at most 90 words, plainly, numbers first. No preamble, no hedging boilerplate.
- Every sentence must be supported by the cited ids. Cite 1-4 ids that carry the answer.
- If the facts don't answer the question, set answerable=false and say in one sentence what is missing.
- Never use outside knowledge, news, or opinions about the stock price."""

ASK_SCHEMA = {"type": "object", "properties": {
    "answerable": {"type": "boolean"},
    "answer": {"type": "string"},
    "cite": {"type": "array", "items": {"type": "string"}},
}, "required": ["answerable", "answer", "cite"]}


def _numbers(v: dict) -> list[tuple[str, str]]:
    """Plain-language facts from the Vitals, each with an id the model can cite."""
    lq, t, cq, bs = v["latest_quarter"], v["trajectory"], v["cash_quality"], v["balance_sheet"]
    facts = []
    if lq:
        facts.append(f"{lq.get('fq')}: revenue Rs {lq.get('revenue')} Cr ({lq.get('revenue_yoy')}% YoY), "
                     f"operating margin {lq.get('ebitda_margin')}%, PAT Rs {lq.get('pat')} Cr ({lq.get('pat_yoy')}% YoY)")
    for q in t["quarters"][-6:-1]:
        facts.append(f"{q['fq']}: revenue Rs {q['revenue']} Cr, PAT Rs {q['pat']} Cr, operating margin {q['margin']}%")
    facts.append(f"5-year revenue CAGR {t['revenue_cagr_5y']}%, 5-year profit CAGR {t['pat_cagr_5y']}%")
    if cq.get("cfo_to_pat_5y") is not None:
        facts.append(f"Operating cash flow was {cq['cfo_to_pat_5y']}% of profit over {cq['cfo_to_pat_years']} years")
    if bs and bs["de"]:
        facts.append(f"Debt to equity {bs['de'][-1]}x ({bs['periods'][-1]}); working-capital days "
                     f"{bs['working_capital_days'][-1]} ({bs['ratio_periods'][-1]})")
    # flags restate figures already listed (cash conversion, margin), so add only the ones that are new
    facts += [f["text"] for f in v["flags"] if not re.search(r"operating cash|Operating margin|Revenue [+-]", f["text"])]
    return [(f"n{i}", f) for i, f in enumerate(facts, 1)]


def ask(symbol: str, question: str) -> dict:
    with connect() as c:
        row = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    if not row:
        raise LookupError(symbol)
    L = json.loads(row["data"])
    v = vitals(symbol)
    claims = L.get("claims", {})
    nums = _numbers(v)
    ctx = "\n".join(f"{cid} [{c['fq']} {c['kind']}] {c['statement']} | quote: \"{c['quote'][:220]}\""
                    for cid, c in claims.items())
    prompt = (f"Company: {v['name']} ({symbol}). Question: {question.strip()[:300]}\n\n"
              f"Claims from management's calls:\n{ctx}\n\nFigures from reported financials:\n"
              + "\n".join(f"{i} {f}" for i, f in nums))
    meta = {}
    out = llm.generate("ask", prompt, purpose="ask", schema=ASK_SCHEMA, system=ASK_SYSTEM, meta=meta)
    num_map = dict(nums)
    cites = []
    for i in out.get("cite", [])[:4]:
        if i in claims:
            c = claims[i]
            cites.append({"id": i, "kind": "claim", "fq": c["fq"], "page": c["page"], "url": c["source_url"],
                          "source_kind": c.get("source_kind"), "quote": c["quote"]})
        elif i in num_map:
            cites.append({"id": i, "kind": "number", "text": num_map[i]})
    answerable = out.get("answerable", False)
    # ids render as receipts below, so strip them from the prose: "(c17)", "(c3, n2)", "(6.5% CAGR, n7)"
    text = re.sub(r"(?:,\s*|\s*;\s*|\s+)?\b[cn]\d{1,3}\b", "", out.get("answer", ""))
    text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
    text = re.sub(r"\s+([.,;)])", r"\1", text).strip()
    return {"answerable": answerable, "answer": text, "cites": cites if answerable else [], "model": meta.get("model")}


def suggestions(symbol: str) -> list[str]:
    """Questions worth asking this company: its most contested promises first, then two staples."""
    with connect() as c:
        row = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    qs = []
    if row:
        L = json.loads(row["data"])
        for t in L.get("threads", []):
            if t["verdict"] in ("missed", "moved", "dropped") and len(qs) < 2:
                topic = t["topic"]
                if len(topic) > 1 and topic[0].isupper() and topic[1].islower():  # keep 'VAM-VAE', 'Q4 FY26'
                    topic = topic[0].lower() + topic[1:]
                tail = "" if re.search(r"guid|target|promise|goal|commitment", topic, re.I) else " promise"
                qs.append(f"What happened to the {topic}{tail}?")
    return qs + ["What has management guided for this year?", "Do profits turn into cash?"]
