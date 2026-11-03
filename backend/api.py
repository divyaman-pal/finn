"""HTTP API. Reads are served from SQLite (instant, free); only a Dossier for a never-seen ticker spends tokens.

    uv run uvicorn backend.api:app --port 8000
"""
import json
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ask, jobs, llm
from .brief import edition
from .config import ROOT
from .db import connect, init_db
from .financials import vitals
from .market import day_stats, delete_rule, rules, save_rule

init_db()
app = FastAPI(title="FINN")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_TICKER = re.compile(r"^[A-Z0-9&\-]{1,20}$")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/brief")
def brief(hours: int = 24):
    return edition(hours=max(1, min(hours, 24 * 30)))


@app.get("/api/companies")
def companies():
    with connect() as c:
        rows = c.execute("""SELECT c.symbol, c.name, c.sector, c.weight, t.data AS ledger
                            FROM companies c LEFT JOIN fin_tables t ON t.symbol=c.symbol AND t.section='ledger'
                            ORDER BY c.weight IS NULL, c.weight DESC, c.symbol""").fetchall()
    out = []
    for r in rows:
        tally, headline = {}, None
        if r["ledger"]:
            L = json.loads(r["ledger"])
            headline = L.get("headline")
            for t in L.get("threads", []):
                tally[t["verdict"]] = tally.get(t["verdict"], 0) + 1
        last = (day_stats(r["symbol"]) or [{}])[-1]
        out.append({"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "weight": r["weight"],
                    "has_ledger": bool(r["ledger"]), "tally": tally, "headline": headline,
                    "price": last.get("close"), "ret": last.get("ret"), "date": last.get("date")})
    return out


@app.get("/api/dossier/{symbol}")
def dossier(symbol: str):
    symbol = symbol.upper().strip()
    if not _TICKER.match(symbol):
        raise HTTPException(400, "Not a valid NSE symbol")
    with connect() as c:
        led = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    if led:
        return {"status": "ready", "vitals": vitals(symbol), "ledger": json.loads(led["data"]),
                "questions": ask.suggestions(symbol)}
    state, error = jobs.status(symbol)
    if state == "error":
        raise HTTPException(404, error)
    if state == "none":
        jobs.start(symbol)
    try:
        partial = vitals(symbol)
    except LookupError:
        partial = None
    return {"status": "building", "vitals": partial}


class Question(BaseModel):
    q: str


@app.post("/api/ask/{symbol}")
def ask_company(symbol: str, body: Question):
    symbol = symbol.upper().strip()
    if not _TICKER.match(symbol) or not body.q.strip():
        raise HTTPException(400, "Ask a question about a valid NSE symbol")
    try:
        return ask.ask(symbol, body.q)
    except LookupError:
        raise HTTPException(404, "Open the company's research first")
    except llm.LLMUnavailable:
        raise HTTPException(503, "The answering model is busy; try again in a moment")


class Rule(BaseModel):
    id: str
    kind: str
    scope: str = "all"
    threshold: float | None = None
    categories: list[str] | None = None
    on: bool = True
    label: str = ""


@app.get("/api/rules")
def get_rules():
    return rules()


@app.put("/api/rules/{rule_id}")
def put_rule(rule_id: str, rule: Rule):
    return save_rule(rule.model_dump(exclude_none=True) | {"id": rule_id})


@app.delete("/api/rules/{rule_id}")
def del_rule(rule_id: str):
    delete_rule(rule_id)
    return {"ok": True}


@app.get("/api/usage")
def get_usage():
    return llm.usage()


# The built frontend, if present, is served from the same origin: one container, one link.
_DIST = ROOT / "web" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
