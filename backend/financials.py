"""Everything numeric is computed here, in Python, from Screener's standardised tables. No model touches it,
so it costs nothing and can't hallucinate."""
import json
from datetime import date

from .db import connect
from .docs import MONTHS, fy_label


def _table(symbol: str, section: str) -> dict:
    with connect() as c:
        row = c.execute("SELECT data FROM fin_tables WHERE symbol=? AND section=?", (symbol, section)).fetchone()
    return json.loads(row["data"]) if row else {"periods": [], "rows": {}}


def _row(t: dict, *names: str) -> list:
    for n in names:
        if n in t["rows"]:
            return t["rows"][n]
    return [None] * len(t["periods"])


def _pct(a, b, digits=1):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100 if b > 0 else (a - b) / abs(b) * 100, digits)


def _ratio(a, b, digits=1):
    return None if a is None or b in (None, 0) else round(a / b * 100, digits)


def _qdate(label: str) -> date | None:
    mon, _, yr = label.partition(" ")
    return date(int(yr), MONTHS[mon], 1) if yr.isdigit() and mon in MONTHS else None


def is_lender(symbol: str) -> bool:
    return "Financing Profit" in _table(symbol, "quarters")["rows"]


def quarterly_actuals(symbol: str) -> dict:
    t = _table(symbol, "quarters")
    lender = "Financing Profit" in t["rows"]
    rev = _row(t, "Sales", "Revenue")
    ebitda = [None] * len(rev) if lender else _row(t, "Operating Profit")
    pbt, pat = _row(t, "Profit before tax"), _row(t, "Net Profit")
    with connect() as c:
        row = c.execute("SELECT consolidated FROM companies WHERE symbol=?", (symbol,)).fetchone()
    out = []
    for i, p in enumerate(t["periods"]):
        d = _qdate(p)
        if not d or rev[i] is None:
            continue
        yo, qo = i - 4, i - 1
        out.append({
            "period": p, "fq": fy_label(d),
            "revenue": rev[i], "ebitda": ebitda[i], "pbt": pbt[i], "pat": pat[i],
            "ebitda_margin": _ratio(ebitda[i], rev[i]),
            "pat_margin": _ratio(pat[i], rev[i]),
            "revenue_yoy": _pct(rev[i], rev[yo]) if yo >= 0 else None,
            "revenue_qoq": _pct(rev[i], rev[qo]) if qo >= 0 else None,
            "ebitda_yoy": _pct(ebitda[i], ebitda[yo]) if yo >= 0 else None,
            "ebitda_qoq": _pct(ebitda[i], ebitda[qo]) if qo >= 0 else None,
            "pbt_yoy": _pct(pbt[i], pbt[yo]) if yo >= 0 else None,
            "pbt_qoq": _pct(pbt[i], pbt[qo]) if qo >= 0 else None,
            "pat_yoy": _pct(pat[i], pat[yo]) if yo >= 0 else None,
            "pat_qoq": _pct(pat[i], pat[qo]) if qo >= 0 else None,
        })
    return {"lender": lender, "label": "consolidated" if row and row["consolidated"] else "standalone",
            "quarters": out}


def _cagr(series: list, years: int):
    vals = [v for v in series if v is not None]
    if len(vals) <= years or vals[-1 - years] <= 0 or vals[-1] <= 0:
        return None
    return round(((vals[-1] / vals[-1 - years]) ** (1 / years) - 1) * 100, 1)


def vitals(symbol: str) -> dict:
    """The Dossier's first screen: snapshot, trajectory, balance sheet, cash quality — plus plain-language flags."""
    with connect() as c:
        co = c.execute("SELECT * FROM companies WHERE symbol=?", (symbol,)).fetchone()
    if not co:
        raise LookupError(symbol)
    pl, bs, cf, rt, sh = (_table(symbol, s) for s in ("profit-loss", "balance-sheet", "cash-flow", "ratios", "shareholding"))
    act = quarterly_actuals(symbol)
    lender = act["lender"]

    # annual P&L, excluding the TTM column for trend maths
    years = [p for p in pl["periods"] if p != "TTM"]
    n = len(years)
    sales = _row(pl, "Sales", "Revenue")[:n]
    op = _row(pl, "Operating Profit")[:n]
    pat = _row(pl, "Net Profit")[:n]
    ttm = pl["periods"].index("TTM") if "TTM" in pl["periods"] else None

    eq = [(a or 0) + (b or 0) for a, b in zip(_row(bs, "Equity Capital"), _row(bs, "Reserves"))]
    debt = _row(bs, "Borrowings", "Borrowing")
    de = [round(d / e, 2) if d is not None and e else None for d, e in zip(debt, eq)]

    cfo = _row(cf, "Cash from Operating Activity")
    fcf = _row(cf, "Free Cash Flow")
    cf_years = cf["periods"]
    pat_by_year = dict(zip(years, pat))
    conv = [_ratio(c_, pat_by_year.get(y)) for y, c_ in zip(cf_years, cfo)]
    # Cash conversion only means something over profitable years: use the latest unbroken run of them (max 5).
    run = []
    for y, c_ in reversed(list(zip(cf_years, cfo))):
        p = pat_by_year.get(y)
        if c_ is None or p is None or p <= 0 or len(run) == 5:
            break
        run.append((c_, p))
    conv5 = _ratio(sum(a for a, _ in run), sum(b for _, b in run)) if len(run) >= 2 else None
    conv_years = len(run)

    q = act["quarters"]
    latest = q[-1] if q else {}
    flags = []  # deterministic, plain-language observations; each one is a fact, not an opinion
    if len(q) >= 5 and latest.get("ebitda_margin") is not None and q[-5].get("ebitda_margin") is not None:
        d = round(latest["ebitda_margin"] - q[-5]["ebitda_margin"], 1)
        if abs(d) >= 1.5:
            flags.append({"tone": "bad" if d < 0 else "good",
                          "text": f"Operating margin {'down' if d < 0 else 'up'} {abs(d)} pts YoY to {latest['ebitda_margin']}% in {latest['fq']}"})
    if latest.get("revenue_yoy") is not None and abs(latest["revenue_yoy"]) >= 10:
        flags.append({"tone": "good" if latest["revenue_yoy"] > 0 else "bad",
                      "text": f"Revenue {'+' if latest['revenue_yoy'] > 0 else ''}{latest['revenue_yoy']}% YoY in {latest['fq']}"})
    if conv5 is not None and not lender:
        if conv5 < 70:
            flags.append({"tone": "bad", "text": f"Only {conv5:.0f}% of {conv_years}-yr profit turned into operating cash"})
        elif conv5 >= 100:
            flags.append({"tone": "good", "text": f"Cash backs profits: {conv_years}-yr operating cash = {conv5:.0f}% of PAT"})
    if not lender and de and de[-1] is not None and len(de) > 1 and de[-2] is not None and de[-1] - de[-2] >= 0.2:
        flags.append({"tone": "bad", "text": f"Debt/equity rose to {de[-1]}x from {de[-2]}x"})
    prom = _row(sh, "Promoters")
    if prom and len(prom) >= 5 and prom[-1] is not None and prom[-5] is not None and abs(prom[-1] - prom[-5]) >= 1:
        d = round(prom[-1] - prom[-5], 2)
        flags.append({"tone": "bad" if d < 0 else "good", "text": f"Promoter stake {'down' if d < 0 else 'up'} {abs(d)} pts in a year to {prom[-1]}%"})

    return {
        "symbol": symbol, "name": co["name"], "sector": co["sector"], "industry": co["industry"],
        "about": co["about"], "ratios": json.loads(co["ratios"] or "{}"), "weight": co["weight"],
        "lender": lender, "basis": act["label"],
        "latest_quarter": latest,
        "ttm": {"revenue": _row(pl, "Sales", "Revenue")[ttm] if ttm is not None else None,
                "pat": _row(pl, "Net Profit")[ttm] if ttm is not None else None},
        "trajectory": {
            "years": years[-8:], "revenue": sales[-8:], "pat": pat[-8:],
            "op_margin": [_ratio(a, b) for a, b in zip(op, sales)][-8:] if not lender else None,
            "revenue_cagr_5y": _cagr(sales, 5), "pat_cagr_5y": _cagr(pat, 5),
            "quarters": [{"fq": x["fq"], "revenue": x["revenue"], "pat": x["pat"], "margin": x["ebitda_margin"]} for x in q[-8:]],
        },
        "balance_sheet": None if lender else {
            "periods": bs["periods"][-5:], "debt": debt[-5:], "equity": eq[-5:], "de": de[-5:],
            "working_capital_days": _row(rt, "Working Capital Days")[-5:],
            "cash_conversion_cycle": _row(rt, "Cash Conversion Cycle")[-5:],
            "ratio_periods": rt["periods"][-5:],
        },
        "cash_quality": {
            "periods": cf_years[-6:], "cfo": cfo[-6:], "fcf": fcf[-6:], "cfo_to_pat": conv[-6:],
            "cfo_to_pat_5y": conv5, "cfo_to_pat_years": conv_years,
        },
        "shareholding": {"periods": sh["periods"][-5:], "promoters": prom[-5:] if prom else []},
        "flags": flags,
    }
