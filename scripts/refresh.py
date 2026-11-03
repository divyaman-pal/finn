"""The Push pipeline end to end: fresh data -> triage -> rich cards. Safe to re-run; everything is incremental.

    uv run python -m scripts.refresh            # portfolio
    uv run python -m scripts.refresh --seed     # then refresh the committed seed snapshot
"""
import shutil
import sys
import time
from datetime import datetime, timedelta

from backend.cards import enrich
from backend.config import DB_PATH, PORTFOLIO, SEED_DB
from backend.db import init_db
from backend.llm import usage
from backend.sources.filings import ingest_filings
from backend.sources.prices import ingest_prices
from backend.triage import triage_pending


def main(argv: list[str]) -> None:
    init_db(use_seed=False)
    t = time.time()
    if "--no-fetch" not in argv:
        for s in ["NIFTY", *PORTFOLIO]:
            try:
                ingest_prices(s)
                if s != "NIFTY":
                    ingest_filings(s)
            except Exception as e:
                print(f"{s}: fetch failed ({type(e).__name__})", flush=True)
            time.sleep(0.3)
    print("fetched", round(time.time() - t), "s", flush=True)
    print("triaged", triage_pending(list(PORTFOLIO)), round(time.time() - t), "s", flush=True)
    since = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%S")
    print("cards", enrich(list(PORTFOLIO), since=since), round(time.time() - t), "s", flush=True)
    print("usage", usage()["total_usd"], "USD at list price")
    if "--seed" in argv:
        shutil.copy(DB_PATH, SEED_DB)
        print("seed updated")


if __name__ == "__main__":
    main(sys.argv[1:])
