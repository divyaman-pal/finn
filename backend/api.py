"""HTTP API. Reads are served from SQLite (instant, free); only a Dossier for a never-seen ticker spends tokens.

    uv run uvicorn backend.api:app --port 8000
"""
import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm
from .brief import edition
from .config import ROOT
from .db import connect, init_db
from .financials import vitals
from .ledger import build_ledger
from .market import delete_rule, rules, save_rule

init_db()
app = FastAPI(title="FINN")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_TICKER = re.compile(r"^[A-Z0-9&\-]{1,20}$")
_building: dict[str, str] = {}   # symbol -> "running" | "error: ..." for dossiers being built in the background


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
        out.append({"symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "weight": r["weight"],
                    "has_ledger": bool(r["ledger"]), "tally": tally, "headline": headline})
    return out


def _build(symbol: str) -> None:
    """Any NSE ticker: fetch its fundamentals and documents, then build the ledger. Runs in the background."""
    from .sources.filings import ingest_filings
    from .sources.prices import ingest_prices
    from .sources.screener import ingest_screener
    try:
        with connect() as c:
            known = c.execute("SELECT 1 FROM companies WHERE symbol=?", (symbol,)).fetchone()
        if not known:
            ingest_screener(symbol)
            ingest_prices(symbol)
            ingest_filings(symbol)
        build_ledger(symbol)
        _building.pop(symbol, None)
    except LookupError:
        _building[symbol] = "error: not found on Screener — check the NSE symbol"
    except Exception as e:
        _building[symbol] = f"error: {type(e).__name__}: {str(e)[:160]}"


@app.get("/api/dossier/{symbol}")
def dossier(symbol: str):
    symbol = symbol.upper().strip()
    if not _TICKER.match(symbol):
        raise HTTPException(400, "Not a valid NSE symbol")
    with connect() as c:
        led = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section='ledger'", (symbol,)).fetchone()
    if led:
        return {"status": "ready", "vitals": vitals(symbol), "ledger": json.loads(led["data"])}
    state = _building.get(symbol)
    if state and state.startswith("error"):
        _building.pop(symbol, None)
        raise HTTPException(404, state[7:])
    if not state:
        _building[symbol] = "running"
        threading.Thread(target=_build, args=(symbol,), daemon=True).start()
    try:
        partial = vitals(symbol)
    except LookupError:
        partial = None
    return {"status": "building", "vitals": partial}


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
