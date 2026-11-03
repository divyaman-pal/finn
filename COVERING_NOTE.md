# FINN — covering note

**Live:** https://finn-jteu.onrender.com · **Code:** https://github.com/divyaman-pal/finn

## What I built

An investor's morning paper that keeps score of management.

The brief says the scarce skill is filtering. Most tools filter by *type* of filing. FINN filters by **consequence for this investor**: a signal that multiplies how heavy the event is, how material this particular filing is, how big the position is, and how the market actually reacted (move vs Nifty, volume vs normal). The Brief opens with a count — *"Five things matter. 7 filed away"* — and a quiet day says so.

The second idea is the **Promise Ledger**. The brief's worked example (promised vs delivered, four quarters) is the part I built deepest, because it's where analysis differs from summary. For every company FINN reads the last four earnings calls, extracts every concrete guidance statement with its exact quote and page, and follows each one forward: **delivered, missed, goalposts moved, quietly dropped,** or pending. *Quietly dropped* — a promise management simply stops mentioning — turned out to be the most revealing verdict (e.g. Sun Pharma's "on track" US launch that never came up again; Infosys trimming its revenue guide three calls running).

The two halves meet in the results card: when results land, FINN shows Revenue / EBITDA / PBT / PAT QoQ and YoY *and* what management had promised for them.

## Decisions and trade-offs

- **Two workflows, done well, over eight shallow ones.** Every Dossier section on the brief's menu is covered, but the Ledger is the centrepiece; I cut a general chat box, voice and a portfolio screen to keep it thin-but-working.
- **No model touches a number it doesn't have to.** Signal scores, QoQ/YoY, margins, cash conversion, debt ratios: Python. Models read text; Python does arithmetic.
- **Trust is built in, not claimed.** Every ledger quote is verified to exist on the page cited (unverifiable ones are dropped). Every results card is reconciled against reported figures — this caught statements in ₹ lakh and ₹ million, scanned PDFs, OCR noise, and revenue definitions that differ (ITC's gross revenue, banks). If FINN can't read a filing reliably, it says so and uses the standardised series.
- **Model routing by what the step needs.** ~93% of tokens go to Gemini Flash-Lite on the free tier (bulk extraction). One Claude Opus 5.5 call per company does the judgement — threading promises across quarters — at ~$0.085. Everything is cached by input hash. Total spend for 22 companies, 1,087 claims and 817 triaged filings: ~$2.26 at list prices, most of it one-time.
- **Triage is routed by cost too.** Rules settle routine paperwork for free; batched one-liners go to the cheap model; only opaque filings ("…informed the Exchange about General Updates") get their PDF's first page read. That peek is what surfaced Asian Paints starting production at Dahej, filed as "Updates".
- **Primary sources only on the pull side** — transcripts, presentations, filings, standardised financials. I deliberately ignored Screener's own AI concall summaries. Push-side bios use web search, as the brief allows.
- **Explained moves.** A price/volume tripwire looks back a week for the filing the market was reacting to. Only genuinely unexplained moves are reported as such.
- **Honest gaps.** ITC holds no earnings calls (FINN falls back to presentations and says so). Maruti files cover letters that link to dead pages — the ledger names which calls it couldn't read rather than guessing.

## Deliberately left out

Intraday data, news, user accounts, native push notifications, broker integration, chat. Also OCR: scanned results PDFs fall back to the standardised numbers (labelled) rather than a slow OCR pass on a free server.

## Where I'd take it next

1. **Scheduled refresh + real push** (web push / WhatsApp) for tripwires, with a morning edition at 8:30.
2. **Credibility over time** — a per-management score across years, and across CEO changes.
3. **Cross-checks between push and pull** — e.g. a capex "commenced production" filing automatically resolving a "moved" ledger thread.
4. **Peer ledgers** — whose guidance is most reliable within a sector.
5. **OCR for scanned filings** and an evaluation set of hand-checked ledgers to measure extraction precision as models change.

## How I worked

Built with Claude Code end to end — research on existing tools and other public FINN attempts, the plan, all code, and verification against live data. The AI build history (this conversation) is attached.
