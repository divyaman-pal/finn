"""SQLite storage. One file, no server; the seed copy ships in the repo so the demo never starts empty."""
import json
import shutil
import sqlite3
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH, SEED_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    sector      TEXT,
    industry    TEXT,
    bse_code    TEXT,
    about       TEXT,
    ratios      TEXT,          -- JSON {name: value} from Screener's top ratios
    consolidated INTEGER,      -- 1 if the financials are consolidated
    weight      REAL,          -- portfolio weight %, NULL if not held
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS prices (
    symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS filings (
    id        TEXT PRIMARY KEY,  -- NSE seq_id
    symbol    TEXT,
    ts        TEXT,              -- ISO timestamp the exchange disseminated it
    nse_desc  TEXT,              -- NSE's own (coarse) subject
    text      TEXT,              -- NSE's one-line description
    url       TEXT,              -- attachment PDF
    size      TEXT,
    category  TEXT,              -- our classification (filled by the triage step)
    summary   TEXT,
    detail    TEXT               -- JSON payload for rich cards (results numbers, bio, ...)
);
CREATE INDEX IF NOT EXISTS filings_sym_ts ON filings(symbol, ts);
CREATE TABLE IF NOT EXISTS fin_tables (
    symbol  TEXT,
    section TEXT,               -- quarters | profit-loss | balance-sheet | cash-flow | ratios | shareholding
    data    TEXT,               -- JSON {"periods": [...], "rows": {metric: [values]}}
    PRIMARY KEY (symbol, section)
);
CREATE TABLE IF NOT EXISTS documents (
    url     TEXT PRIMARY KEY,
    symbol  TEXT,
    kind    TEXT,               -- transcript | annual_report | ppt
    period  TEXT,               -- e.g. "Oct 2026" or "2026"
    text    TEXT                -- extracted text, filled lazily
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, model TEXT, purpose TEXT, output TEXT,
    in_tokens INTEGER, out_tokens INTEGER, cost_usd REAL, created_at TEXT
);
"""


def init_db(use_seed: bool = True) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if use_seed and not DB_PATH.exists() and SEED_DB.exists():
        shutil.copy(SEED_DB, DB_PATH)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
