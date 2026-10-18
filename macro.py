"""Auswertungen der Macro Data API: Zinskurve, EZB-Kurse, COT-Positionierung."""
from __future__ import annotations

import datetime as dt

import sources as src


def _date(s: str | None) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD")


# ------------------------------------------------------------------ A6 Zinskurve
def _curve_on(day: dt.date | None):
    target = day or dt.date.today()
    for year in (target.year, target.year - 1):
        data = src.treasury_year(year)
        cands = [d for d in data if d <= target]
        if cands:
            d = max(cands)
            if (target - d).days > 10:
                raise ValueError(f"No Treasury curve within 10 days before {target}")
            return d, data[d]
    raise ValueError(f"No Treasury curve available for {target}")


def yield_curve(date: str | None = None) -> dict:
    d, vals = _curve_on(_date(date))
    order = sorted(vals, key=lambda k: src.TENOR_KEYS[k][0])
    s2_10 = vals.get("10y") - vals.get("2y") if "10y" in vals and "2y" in vals else None
    s3m_10 = vals.get("10y") - vals.get("3m") if "10y" in vals and "3m" in vals else None
    shape = "inverted" if s2_10 is not None and s2_10 < 0 else ("flat" if s2_10 is not None and abs(s2_10) < 0.1 else "normal")
    return {"date": d.isoformat(), "unit": "percent",
            "curve": [{"tenor": k, "label": src.TENOR_KEYS[k][1], "yield": vals[k]} for k in order],
            "spread_2y_10y": None if s2_10 is None else round(s2_10, 3),
            "spread_3m_10y": None if s3m_10 is None else round(s3m_10, 3),
            "shape": shape,
            "source": {"data": "U.S. Department of the Treasury, Daily Treasury Par Yield Curve Rates",
                       "license": "Public domain (U.S. Government Work / CC0)"}}


def spread(a: str = "2y", b: str = "10y", date: str | None = None) -> dict:
    a, b = a.lower(), b.lower()
    for t in (a, b):
        if t not in src.TENOR_KEYS:
            raise ValueError(f"tenor must be one of {', '.join(src.TENOR_KEYS)}")
    d, vals = _curve_on(_date(date))
    if a not in vals or b not in vals:
        raise ValueError(f"Tenor not published on {d}")
    return {"date": d.isoformat(), "a": a, "b": b, "yield_a": vals[a], "yield_b": vals[b],
            "spread_b_minus_a": round(vals[b] - vals[a], 3), "inverted": vals[b] < vals[a], "unit": "percent",
            "source": {"data": "U.S. Department of the Treasury, Daily Treasury Par Yield Curve Rates"}}


# ------------------------------------------------------------------ A7 EZB-Kurse
def _rates_on(day: dt.date | None):
    recent = src.ecb_recent()
    target = day or max(recent)
    data = recent if target >= min(recent) else src.ecb_full()
    cands = [d for d in data if d <= target]
    if not cands:
        raise ValueError("No ECB rates before that date (series starts 1999-01-04)")
    d = max(cands)
    if (target - d).days > 7:
        raise ValueError(f"No ECB rates within 7 days before {target}")
    return d, data[d]


def fx_rate(base: str = "EUR", quote: str = "USD", date: str | None = None) -> dict:
    base, quote = base.upper(), quote.upper()
    d, rates = _rates_on(_date(date))
    for c in (base, quote):
        if c not in rates:
            raise ValueError(f"Currency {c} not in ECB reference rates. Available: {', '.join(sorted(rates))}")
    rate = rates[quote] / rates[base]
    return {"date": d.isoformat(), "base": base, "quote": quote, "rate": round(rate, 6),
            "note": "Cross rates are derived from EUR reference rates." if "EUR" not in (base, quote) else "",
            "source": {"data": "Source: ECB statistics (euro foreign exchange reference rates)",
                       "license": "Free reuse with source attribution; values not modified"}}


def convert(amount: float, frm: str, to: str, date: str | None = None) -> dict:
    r = fx_rate(frm, to, date)
    return {**r, "amount": amount, "converted": round(amount * r["rate"], 4)}


def fx_currencies() -> list[str]:
    _, rates = _rates_on(None)
    return sorted(rates)


# ------------------------------------------------------------------ A8 COT
def cot(market: str, weeks: int = 1) -> dict:
    key = market.upper().strip()
    if key not in src.COT_MARKETS:
        raise KeyError(f"Unknown COT market '{market}'. Use one of: {', '.join(src.COT_MARKETS)}")
    if not 1 <= weeks <= 260:
        raise ValueError("weeks must be between 1 and 260")
    code, desc = src.COT_MARKETS[key]
    hist = src.cot_history(code, weeks)
    latest = hist[0]
    chg = None
    if len(src.cot_history(code, 2)) > 1:
        prev = src.cot_history(code, 2)[1]
        if latest["noncommercial"]["net"] is not None and prev["noncommercial"]["net"] is not None:
            chg = latest["noncommercial"]["net"] - prev["noncommercial"]["net"]
    return {"market": key, "description": desc, "cftc_code": code,
            "latest": latest, "noncommercial_net_change_vs_prior_week": chg,
            "history": hist if weeks > 1 else None,
            "note": "Positions as of Tuesday, published Friday by the CFTC.",
            "source": {"data": "CFTC Commitments of Traders, Legacy Futures Only",
                       "license": "Public domain (U.S. Government Work)"}}


def cot_markets() -> list[dict]:
    return [{"market": k, "description": d, "cftc_code": c} for k, (c, d) in src.COT_MARKETS.items()]
