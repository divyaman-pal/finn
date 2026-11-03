# FINN — Financial Investment Agent

A mobile-first agent for a public-markets investor, built for the ENAM Holdings AI Engineer Build Challenge.

**Live:** https://finn-jteu.onrender.com — open it on a phone. Free tier: the first load after idle takes ~50 seconds.

FINN does two things, and both run on one idea: **management makes promises; FINN checks them.**

| | **Brief** (push) | **Research** (pull) |
|---|---|---|
| When | Every day, for your book of 16 stocks | On demand, for **any NSE ticker** |
| Shows | The 3–8 things that matter in a window you pick; everything else filed away | Promise Ledger, Vitals, Bull vs Bear — each claim linked to its page in the source |
| The promise engine | A results card checks this quarter against the last four calls' guidance | The full ledger: delivered, missed, goalposts moved, quietly dropped, pending |

## What it looks like

- **Brief** — "Five things matter." A search box for any company, a strip of today's moves across the book, filter chips (Results / Leadership / Legal / Moves…), ranked story cards, and a "filed away" drawer for routine paperwork. Tap a story for the numbers: Revenue, EBITDA, PBT, PAT, QoQ and YoY, read from the actual results filing and reconciled against reported figures; then the **Promise check**; then how the market took it.
- **Research** — your portfolio with prices, day moves and each company's promise record; search any NSE symbol (a company never seen before builds in ~2 minutes from its filings). Each company page has the Promise Ledger (every promise traced call by call, verbatim quote and page link), Vitals, Bull vs Bear, and **Ask**: questions answered only from that company's own calls and numbers, with receipts.
- **Alerts** — rules written as sentences: *When [any small cap ▾] moves more than [− ±3% +] in a day.*

## Architecture

```
NSE announcements ─┐                                   ┌─ rules (free) ──┐
Yahoo EOD prices ──┼─► SQLite ─► triage ───────────────┼─ cheap model ───┼─► signal score ─► Brief
screener.in ───────┘     │     (3 routes, cheapest     └─ cheap + PDF p1 ┘   (event × materiality ×
 (tables + links to      │      first)                                         position × reaction)
  ARs, transcripts)      │
                         ├─► results card: find the P&L page → cheap model reads 3 columns → Python
                         │   computes EBITDA/QoQ/YoY → reconcile with reported figures (units, basis)
                         ├─► leadership card: Tavily search → cheap model writes a 2-line bio + sources
                         └─► Promise Ledger: 4 calls → cheap model extracts claims with quote + page →
                             Python verifies every quote exists → ONE strong-model call threads promises
                             across quarters → Python re-checks numeric verdicts against reported numbers
```

- **Backend** — Python, FastAPI, SQLite, `httpx`, BeautifulSoup, `pypdf`. `backend/`
- **Frontend** — React + Vite, no UI kit; hand-written CSS, editorial type (Newsreader + Inter), light and dark. `web/`
- **Deploy** — one Docker image; the API serves the built app. `render.yaml` is a Render blueprint.
- **Seed** — `seed/finn_seed.db` is a snapshot of everything already read, so the demo works with no keys and no network.

## Model routing and cost

| Step | Engine | Share of tokens | Spend |
|---|---|---|---|
| Filing triage, claim extraction, results numbers, bios | Gemini Flash-Lite (free tier) | ~93% | ~$0.27 at list price, ₹0 actual |
| Promise Ledger + bull/bear (one call per company) | Claude Opus 5.5 | ~7% | ~$0.085 per company |
| Ask (per question, grounded in extracted claims + numbers) | Claude Haiku 5.5 → Flash-Lite | small | ~$0.002 per question |
| Signal score, Vitals, QoQ/YoY, reconciliation, quote checks | Python | — | 0 |

Every model call is cached on a hash of its input, so nothing is read twice. Fallback chains keep the app working:
Opus → Gemini Flash → Flash-Lite; if a strong answer came from the lite fallback, the ledger is marked and rebuilt later.
`/api/usage` reports spend per model and purpose; each Brief prints what it cost to make.

## Run it

```bash
uv sync                                        # Python 3.12
cp .env.example .env                           # optional: GEMINI_API_KEY, ANTHROPIC_API_KEY, TAVILY_API_KEY
cd web && npm install && npm run build && cd ..
uv run python -m uvicorn backend.api:app --port 8000
```

Open http://localhost:8000. Without keys, everything in the seed works; only new tickers need keys.

Refresh data: `uv run python -m scripts.refresh` (prices, filings, triage, cards) and
`uv run python -m scripts.warm SYMBOL` (ledgers). `--seed` on either updates the committed snapshot.

## Deploy

Render → New → Blueprint → this repo. Add the three keys when asked. Or anywhere with Docker:
`docker build -t finn . && docker run -p 8000:8000 --env-file .env finn`.

See [COVERING_NOTE.md](COVERING_NOTE.md) for decisions, trade-offs, what's left out and what's next.
