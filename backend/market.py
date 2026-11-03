"""End-of-day market reaction and the investor's own tripwires. Pure Python over the prices table."""
import json
from datetime import date

from .db import connect, dumps

# Default tripwires: the brief's examples. The investor edits these in the app.
DEFAULT_RULES = [
    {"id": "move", "kind": "price_move", "scope": "all", "threshold": 4.0, "on": True,
     "label": "Any holding moves more than ±4% in a day"},
    {"id": "volume", "kind": "volume_spike", "scope": "all", "threshold": 2.0, "on": True,
     "label": "Volume above 2× its 20-day average"},
    {"id": "smallcap", "kind": "price_move", "scope": "small", "threshold": 3.0, "on": False,
     "label": "Any small cap moves more than ±3%"},
    {"id": "filings", "kind": "filing", "scope": "all", "categories": ["results", "M&A", "management_change", "fund_raise",
                                                                        "litigation", "credit_rating", "pledging"],
     "on": True, "label": "Material filings: results, M&A, leadership, fund raise, litigation, ratings, pledges"},
]


def rules() -> list[dict]:
    with connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS rules (id TEXT PRIMARY KEY, data TEXT)")
        rows = c.execute("SELECT data FROM rules").fetchall()
        if not rows:
            c.executemany("INSERT INTO rules VALUES (?,?)", [(r["id"], dumps(r)) for r in DEFAULT_RULES])
            return [dict(r) for r in DEFAULT_RULES]
    return [json.loads(r["data"]) for r in rows]


def save_rule(rule: dict) -> dict:
    rules()  # ensure table + defaults exist
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO rules VALUES (?,?)", (rule["id"], dumps(rule)))
    return rule


def delete_rule(rule_id: str) -> None:
    with connect() as c:
        c.execute("DELETE FROM rules WHERE id=?", (rule_id,))


def cap_bucket(market_cap_text: str | None) -> str:
    """Screener shows '₹ 4,62,199 Cr.'; SEBI-style cutoffs approximated by size."""
    try:
        cr = float("".join(ch for ch in (market_cap_text or "") if ch.isdigit() or ch == "."))
    except ValueError:
        return "unknown"
    return "large" if cr >= 100_000 else "mid" if cr >= 30_000 else "small"


def day_stats(symbol: str, upto: str | None = None) -> list[dict]:
    """Per trading day: return %, return vs Nifty, volume ÷ trailing 20-day average."""
    with connect() as c:
        px = c.execute("SELECT date, close, volume FROM prices WHERE symbol=? ORDER BY date", (symbol,)).fetchall()
        nifty = dict(c.execute("SELECT date, close FROM prices WHERE symbol='NIFTY' ORDER BY date").fetchall())
    out, prev_n = [], None
    nd = sorted(nifty)
    nret = {d: (nifty[d] / nifty[p] - 1) * 100 for p, d in zip(nd, nd[1:])}
    for i in range(1, len(px)):
        d, close, vol = px[i]["date"], px[i]["close"], px[i]["volume"]
        if upto and d > upto:
            break
        ret = (close / px[i - 1]["close"] - 1) * 100
        window = [r["volume"] for r in px[max(0, i - 20):i] if r["volume"]]
        avg = sum(window) / len(window) if window else None
        out.append({"date": d, "close": round(close, 2), "ret": round(ret, 2),
                    "excess": round(ret - nret[d], 2) if d in nret else None,
                    "vol_x": round(vol / avg, 2) if avg and vol else None})
    return out


def reaction(symbol: str, ts: str) -> dict | None:
    """How the stock took a filing: the first close at or after it (after-hours filings land on the next day)."""
    stats = day_stats(symbol)
    day = ts[:10]
    after_close = ts[11:16] > "15:30"
    for s in stats:
        if s["date"] > day or (s["date"] == day and not after_close):
            return s
    return None


def tripped(since: date) -> list[dict]:
    """Price/volume tripwires crossed on any trading day since `since`, for held companies."""
    active = [r for r in rules() if r.get("on") and r["kind"] in ("price_move", "volume_spike")]
    with connect() as c:
        cos = c.execute("SELECT symbol, name, weight, ratios FROM companies WHERE weight IS NOT NULL").fetchall()
    hits = []
    for co in cos:
        bucket = cap_bucket(json.loads(co["ratios"] or "{}").get("Market Cap"))
        for s in day_stats(co["symbol"]):
            if s["date"] < since.isoformat():
                continue
            for r in active:
                if r["scope"] not in ("all", bucket) and r["scope"] != co["symbol"]:
                    continue
                if r["kind"] == "price_move" and abs(s["ret"]) >= r["threshold"]:
                    hits.append({"symbol": co["symbol"], "rule": r["id"], "date": s["date"], **s,
                                 "why": f"{'Up' if s['ret'] > 0 else 'Down'} {abs(s['ret']):.1f}%"
                                        + (f" ({s['excess']:+.1f}% vs Nifty)" if s["excess"] is not None else "")})
                elif r["kind"] == "volume_spike" and (s["vol_x"] or 0) >= r["threshold"]:
                    hits.append({"symbol": co["symbol"], "rule": r["id"], "date": s["date"], **s,
                                 "why": f"Volume {s['vol_x']:.1f}× the 20-day average, price {s['ret']:+.1f}%"})
    # one alert per stock per day, even if several rules fired
    merged = {}
    for h in hits:
        k = (h["symbol"], h["date"])
        if k in merged:
            merged[k]["rules"].append(h["rule"])
            if h["rule"] != merged[k]["rules"][0]:
                merged[k]["why"] += " · " + h["why"]
        else:
            merged[k] = h | {"rules": [h["rule"]]}
    return list(merged.values())
