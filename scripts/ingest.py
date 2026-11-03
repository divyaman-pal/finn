"""Pull prices, filings and fundamentals for the whole demo universe.

    uv run python -m scripts.ingest              # everything
    uv run python -m scripts.ingest INFY TCS     # specific symbols (works for any NSE ticker)
    uv run python -m scripts.ingest --seed       # also refresh the committed seed snapshot
"""
import shutil
import sys
import time

from backend.config import PORTFOLIO, RESEARCH_DEMO, SEED_DB, DB_PATH
from backend.db import init_db
from backend.sources.filings import ingest_filings
from backend.sources.prices import ingest_prices
from backend.sources.screener import ingest_screener


def run(symbol: str) -> None:
    weight = PORTFOLIO.get(symbol)
    out = []
    for label, fn in (("screener", lambda: ingest_screener(symbol, weight)),
                      ("prices", lambda: ingest_prices(symbol)),
                      ("filings", lambda: ingest_filings(symbol))):
        try:
            out.append(f"{label}={fn()}")
        except Exception as e:  # one bad source shouldn't sink the others
            out.append(f"{label}=FAILED({type(e).__name__}: {str(e)[:80]})")
        time.sleep(0.5)  # be polite to free public endpoints
    print(f"{symbol:<11}", " | ".join(out), flush=True)


def main(argv: list[str]) -> None:
    seed = "--seed" in argv
    symbols = [a.upper() for a in argv if not a.startswith("--")] or list(PORTFOLIO) + RESEARCH_DEMO
    init_db(use_seed=False)
    for s in symbols:
        run(s)
    if seed:
        SEED_DB.parent.mkdir(exist_ok=True)
        shutil.copy(DB_PATH, SEED_DB)
        print("seed updated:", SEED_DB)


if __name__ == "__main__":
    main(sys.argv[1:])
