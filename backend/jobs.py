"""Background dossier builds for tickers FINN hasn't seen. Each build runs in its own process, so PDF parsing
(pure Python, CPU-bound) never starves the web server, and job state lives in SQLite so any worker can answer
"is it ready yet?"."""
import multiprocessing as mp
from datetime import datetime, timedelta, timezone

from .db import connect

STALE = timedelta(minutes=12)   # a build that hasn't finished by then died with its process (e.g. a restart)
_ctx = mp.get_context("spawn")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table(c) -> None:
    c.execute("CREATE TABLE IF NOT EXISTS jobs (symbol TEXT PRIMARY KEY, status TEXT, error TEXT, started_at TEXT)")


def _run(symbol: str) -> None:
    """Child process: fetch fundamentals and documents if new, then build the ledger."""
    from .ledger import build_ledger
    from .sources.filings import ingest_filings
    from .sources.prices import ingest_prices
    from .sources.screener import ingest_screener
    try:
        with connect() as c:
            known = c.execute("SELECT 1 FROM companies WHERE symbol=?", (symbol,)).fetchone()
        if not known:
            ingest_screener(symbol)
            for fn in (ingest_prices, ingest_filings):  # nice to have; the ledger doesn't depend on them
                try:
                    fn(symbol)
                except Exception:
                    pass
        build_ledger(symbol)
        with connect() as c:
            c.execute("DELETE FROM jobs WHERE symbol=?", (symbol,))
    except LookupError:
        _fail(symbol, "Not found on Screener. Check the NSE symbol.")
    except Exception as e:
        _fail(symbol, f"{type(e).__name__}: {str(e)[:160]}")


def _fail(symbol: str, msg: str) -> None:
    with connect() as c:
        c.execute("UPDATE jobs SET status='error', error=? WHERE symbol=?", (msg, symbol))


def status(symbol: str) -> tuple[str, str | None]:
    """'none' | 'running' | ('error', message). An error is reported once, then cleared so a retry can start."""
    with connect() as c:
        _table(c)
        row = c.execute("SELECT status, error, started_at FROM jobs WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            return "none", None
        if row["status"] == "error":
            c.execute("DELETE FROM jobs WHERE symbol=?", (symbol,))
            return "error", row["error"]
        if datetime.now(timezone.utc) - datetime.fromisoformat(row["started_at"]) > STALE:
            c.execute("DELETE FROM jobs WHERE symbol=?", (symbol,))
            return "none", None
        return "running", None


def start(symbol: str) -> None:
    with connect() as c:
        _table(c)
        # INSERT OR IGNORE: if two requests race, only one build starts
        if c.execute("INSERT OR IGNORE INTO jobs VALUES (?, 'running', NULL, ?)", (symbol, _now())).rowcount == 0:
            return
    _ctx.Process(target=_run, args=(symbol,), daemon=True).start()
