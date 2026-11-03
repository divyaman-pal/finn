"""The Brief: one edition for a time window. Ranks what matters, files away the rest.

signal = event weight × materiality × position weight × market reaction
  event weight   — how much this kind of filing tends to matter (results > M&A > leadership > ... > paperwork)
  materiality    — the triage model's read of this particular filing (high / medium / low)
  position       — bigger holdings matter more (dampened, so a 2% position isn't invisible)
  reaction       — the market's own verdict: move vs Nifty and volume vs normal on the first close after the filing
A price/volume tripwire with no filing behind it becomes its own story: "moved, and nothing filed explains it".
"""
import json
import math
import re
from datetime import datetime, timedelta, timezone

from .db import connect
from .market import day_stats, reaction, rules, tripped

IST = timezone(timedelta(hours=5, minutes=30))

EVENT = {"results": 1.0, "M&A": 0.9, "management_change": 0.85, "pledging": 0.8, "fund_raise": 0.75,
         "litigation": 0.7, "credit_rating": 0.6, "insider_trading": 0.6, "capex": 0.6, "bonus_split": 0.5,
         "press_release": 0.4, "dividend": 0.35, "earnings_call": 0.3, "postal_ballot": 0.2, "agm_egm": 0.15,
         "investor_meetings": 0.15, "unclassified": 0.05}
MATERIALITY = {"high": 1.0, "medium": 0.55, "low": 0.2}
MATTERS = 0.33        # signal at or above this makes the front page
MAX_STORIES = 8

LABELS = {"results": "Results", "M&A": "M&A", "management_change": "Leadership", "pledging": "Pledge",
          "fund_raise": "Fund raise", "litigation": "Legal & regulatory", "credit_rating": "Credit rating",
          "insider_trading": "Insider trade", "capex": "Capacity", "bonus_split": "Bonus / split",
          "press_release": "Business update", "dividend": "Dividend", "earnings_call": "Earnings call",
          "postal_ballot": "Postal ballot", "agm_egm": "Shareholder meeting", "investor_meetings": "Investor meetings",
          "unclassified": "Paperwork", "market": "Market move"}


def _position(weight: float | None, max_w: float) -> float:
    return 0.6 + 0.4 * math.sqrt((weight or 0) / max_w) if max_w else 1.0


def _reaction_mult(r: dict | None) -> float:
    if not r:
        return 1.0
    move = abs(r["excess"] if r.get("excess") is not None else r["ret"])
    vol = max((r.get("vol_x") or 1) - 1, 0)
    return 1 + 0.5 * min(move / 4, 1) + 0.5 * min(vol / 2, 1)


def _fmt(v, unit="%"):
    return f"{v:+.1f}{unit}" if v is not None else "n/a"


def card_lines(card: dict | None, fallback_head: str, fallback_why: str) -> tuple[str, str]:
    """Write headline and why from the card's numbers, not from a model: concrete and never generic."""
    if not card:
        return fallback_head, fallback_why
    if card.get("kind") == "results" and card.get("lines"):
        ln = {l["label"]: l for l in card["lines"]}
        rev, pat = ln.get("Revenue", {}), ln.get("PAT", {})
        e = ln.get("EBITDA") or ln.get("Pre-provision profit") or {}
        fq = (card.get("check") or {}).get("fq") or "Quarterly"
        head = f"{fq} results: PAT {_fmt(pat.get('yoy'))} YoY, revenue {_fmt(rev.get('yoy'))}"
        bits = [f"Revenue {_fmt(rev.get('yoy'))} YoY, {_fmt(rev.get('qoq'))} QoQ"]
        if card.get("margin") is not None and not card.get("lender"):
            prior = (e["year_ago"] / rev["year_ago"] * 100) if e.get("year_ago") and rev.get("year_ago") else None
            bits.append(f"EBITDA margin {card['margin']}%" + (f" ({card['margin'] - prior:+.1f} pts YoY)" if prior else ""))
        bits.append(f"PAT {_fmt(pat.get('yoy'))} YoY")
        return head, " · ".join(bits)
    if card.get("kind") == "management_change" and card.get("previous"):
        return fallback_head, f"{card['person']}: previously {card['previous']}."
    return fallback_head, fallback_why


def _explaining_filing(symbol: str, move_date: str) -> dict | None:
    """The filing the market was reacting to: a material filing in the week before whose first close is the move day."""
    since = (datetime.fromisoformat(move_date) - timedelta(days=7)).strftime("%Y-%m-%d")
    with connect() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM filings WHERE symbol=? AND ts >= ? AND ts <= ? AND category IS NOT NULL ORDER BY ts DESC",
            (symbol, since, move_date + "T23:59:59"))]
    best = None
    for f in rows:
        d = json.loads(f["detail"] or "{}")
        if d.get("materiality") not in ("high", "medium"):
            continue
        r = reaction(symbol, f["ts"])
        if r and r["date"] == move_date:
            rank = (d.get("materiality") == "high", EVENT.get(f["category"], 0), bool(d.get("card")))
            if not best or rank > best[0]:
                best = (rank, f, d)
    return None if not best else best[1] | {"d": best[2]}


def edition(hours: int = 24, now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    since = now - timedelta(hours=hours)
    since_s = since.strftime("%Y-%m-%dT%H:%M:%S")
    watched = {r["id"]: r for r in rules()}
    watch_cats = set(watched.get("filings", {}).get("categories", [])) if watched.get("filings", {}).get("on") else set()

    with connect() as c:
        cos = {r["symbol"]: dict(r) for r in c.execute("SELECT symbol, name, weight FROM companies WHERE weight IS NOT NULL")}
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM filings WHERE ts >= ? AND symbol IN (SELECT symbol FROM companies WHERE weight IS NOT NULL) "
            "ORDER BY ts DESC", (since_s,))]
        cost = c.execute("SELECT COALESCE(SUM(cost_usd),0) FROM llm_cache WHERE purpose IN ('triage','results_extract','bio') "
                         "AND created_at >= ?", ((since.astimezone(timezone.utc)).isoformat(timespec='seconds'),)).fetchone()[0]
    max_w = max((c_["weight"] for c_ in cos.values()), default=1)

    # 1. Fold duplicates: companies often file the same event 2-3 times (outcome, results, press release).
    groups: dict[tuple, list] = {}
    pending = 0
    for f in rows:
        if not f["category"]:
            pending += 1
            continue
        f["d"] = json.loads(f["detail"] or "{}")
        key = (f["symbol"], f["category"], f["ts"][:10])
        groups.setdefault(key, []).append(f)

    stories, filed = [], {}
    for (sym, cat, _), fs in groups.items():
        # lead with the filing that has a rich card, then the most material, then the earliest
        fs.sort(key=lambda f: (not (f["d"].get("card") or {}).get("verified", bool(f["d"].get("card"))),
                               not f["d"].get("card"), ["high", "medium", "low"].index(f["d"].get("materiality", "low")),
                               f["ts"]))
        lead = fs[0]
        d = lead["d"]
        mat = max((x["d"].get("materiality", "low") for x in fs), key=lambda m: MATERIALITY[m])
        react = reaction(sym, lead["ts"])
        parts = {"event": EVENT.get(cat, 0.1), "materiality": MATERIALITY[mat],
                 "position": round(_position(cos[sym]["weight"], max_w), 2), "reaction": round(_reaction_mult(react), 2)}
        score = round(parts["event"] * parts["materiality"] * parts["position"] * parts["reaction"], 3)
        head, why = card_lines(d.get("card"), d.get("headline") or lead["text"], d.get("why") or "")
        stems = lambda s: {w[:5] for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in ("the", "of", "a", "an", "mr", "ms", "as", "from", "to")}
        hw, ww = stems(head), stems(why)
        if ww and len(hw & ww) / len(ww) > 0.6:
            why = ""  # a why that only restates the headline is noise
        item = {"id": lead["id"], "kind": "filing", "symbol": sym, "name": cos[sym]["name"], "weight": cos[sym]["weight"],
                "category": cat, "label": LABELS.get(cat, cat), "materiality": mat, "ts": lead["ts"],
                "headline": head, "why": why,
                "url": lead["url"], "card": d.get("card"), "reaction": react, "score": score, "parts": parts,
                "watched": cat in watch_cats and mat == "high",
                "also": [{"headline": x["d"].get("headline"), "url": x["url"], "ts": x["ts"]} for x in fs[1:]]}
        if score >= MATTERS or item["watched"]:
            stories.append(item)
        else:
            filed.setdefault(item["label"], []).append(item)

    # 2. Tripwires. A move on a day a story exists for that stock explains itself. Otherwise look back a week for
    #    the filing the market was reacting to; only a move with no such filing is reported as unexplained.
    #    One market story per stock: the strongest day leads, other days ride along.
    explained = {(s["symbol"], (s["reaction"] or {}).get("date")) for s in stories}
    market: dict[str, dict] = {}
    for h in sorted(tripped(since.date()), key=lambda h: -_reaction_mult(h)):
        sym = h["symbol"]
        if sym not in cos:
            continue
        if (sym, h["date"]) in explained:
            for s in stories:
                if s["symbol"] == sym and (s["reaction"] or {}).get("date") == h["date"]:
                    s["tripwire"] = h["why"]
            continue
        if sym in market:
            market[sym]["also"].append({"headline": f"{h['date']}: {h['why']}"})
            continue
        cause = _explaining_filing(sym, h["date"])
        parts = {"event": 0.5, "materiality": 1.0, "position": round(_position(cos[sym]["weight"], max_w), 2),
                 "reaction": round(_reaction_mult(h), 2)}
        big_move = "move" in h["rules"] or "smallcap" in h["rules"]
        head = (f"{'Up' if h['ret'] > 0 else 'Down'} {abs(h['ret']):.1f}%" if big_move else f"Volume {h['vol_x']:.1f}× normal")
        if big_move and (h.get("vol_x") or 0) >= 1.5:
            head += f" on {h['vol_x']:.1f}× normal volume"
        elif not big_move:
            head += f", price {h['ret']:+.1f}%"
        story = {"id": f"mkt-{sym}-{h['date']}", "kind": "market", "symbol": sym,
                 "name": cos[sym]["name"], "weight": cos[sym]["weight"], "category": "market",
                 "label": LABELS["market"], "materiality": "high", "ts": h["date"] + "T15:30:00",
                 "headline": head, "why": "No exchange filing in the past week explains the move.",
                 "reaction": {k: h[k] for k in ("date", "ret", "excess", "vol_x", "close")}, "rules": h["rules"],
                 "score": round(parts["event"] * parts["position"] * parts["reaction"], 3), "parts": parts,
                 "watched": True, "also": []}
        if cause:
            dt = datetime.fromisoformat(cause["ts"])
            filed_on = f"{dt.day} {dt.strftime('%b')}"
            cause_head, _ = card_lines(cause["d"].get("card"), cause["d"].get("headline") or cause["text"], "")
            m = re.match(r"(Q\d FY\d\d) results: (.*)", cause_head)
            why = (f"Reacting to {m.group(1)} results filed {filed_on}: {m.group(2)}" if m else
                   f"Reacting to {LABELS.get(cause['category'], cause['category']).lower()} filed {filed_on}: {cause_head}")
            story |= {"why": why, "card": cause["d"].get("card"), "url": cause["url"],
                      "cause_category": cause["category"]}
        market[sym] = story
    stories.extend(market.values())

    stories.sort(key=lambda s: -s["score"])
    overflow = stories[MAX_STORIES:]
    stories = stories[:MAX_STORIES]
    for s in overflow:
        filed.setdefault(s["label"], []).append(s)

    strip = []
    for sym, co in sorted(cos.items(), key=lambda kv: -(kv[1]["weight"] or 0)):
        last = (day_stats(sym) or [{}])[-1]
        strip.append({"symbol": sym, "weight": co["weight"], "ret": last.get("ret"), "vol_x": last.get("vol_x"),
                      "story": any(s["symbol"] == sym for s in stories)})

    return {
        "window": {"hours": hours, "since": since.isoformat(timespec="minutes"), "until": now.isoformat(timespec="minutes")},
        "counts": {"matter": len(stories), "filed": sum(len(v) for v in filed.values()),
                   "filings": len(rows), "pending": pending},
        "stories": stories,
        "filed": [{"label": k, "items": sorted(v, key=lambda x: x["ts"], reverse=True)}
                  for k, v in sorted(filed.items(), key=lambda kv: -len(kv[1]))],
        "strip": strip,
        "cost_usd": round(cost or 0, 4),
    }
