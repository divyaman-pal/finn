"""Pre-build the expensive artefacts so the demo opens instantly (and costs nothing to browse).

    uv run python -m scripts.warm              # ledgers for every company
    uv run python -m scripts.warm ASIANPAINT   # one company
    uv run python -m scripts.warm --seed       # then refresh the committed seed snapshot
"""
import shutil
import sys
import time

from backend.config import DB_PATH, PORTFOLIO, RESEARCH_DEMO, SEED_DB
from backend.db import init_db
from backend.ledger import build_ledger
from backend.llm import usage


def main(argv: list[str]) -> None:
    symbols = [a.upper() for a in argv if not a.startswith("--")] or RESEARCH_DEMO + list(PORTFOLIO)
    force = "--force" in argv
    init_db(use_seed=False)
    for s in symbols:
        t = time.time()
        try:
            L = build_ledger(s, force=force)
            if L["status"] == "ok":
                verdicts = {}
                for th in L["threads"]:
                    verdicts[th["verdict"]] = verdicts.get(th["verdict"], 0) + 1
                print(f"{s:<11} {L['source_kind']:<10} claims={len(L['claims']):<3} {verdicts}  {time.time() - t:.0f}s", flush=True)
            else:
                print(f"{s:<11} {L['status']}", flush=True)
        except Exception as e:
            print(f"{s:<11} FAILED {type(e).__name__}: {str(e)[:150]}", flush=True)
    print("usage:", usage()["total_usd"], "USD at list price")
    if "--seed" in argv:
        shutil.copy(DB_PATH, SEED_DB)
        print("seed updated")


if __name__ == "__main__":
    main(sys.argv[1:])
