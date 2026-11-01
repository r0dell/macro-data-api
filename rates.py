"""A31 Referenzzinsen (SOFR, EFFR, OBFR, €STR) und A38 aktuelle Inflationszahlen (US-CPI, HICP).

Quellen (frei nutzbar):
- Federal Reserve Bank of New York, Reference Rates API (markets.newyorkfed.org). Nutzung nach den
  Terms of Use der NY Fed: Hinweis und Haftungsausschluss in jeder Antwort (siehe NYFED_NOTICE).
- EZB Data Portal (data-api.ecb.europa.eu), €STR, frei mit Quellenangabe.
- U.S. Bureau of Labor Statistics, Public Data API v1 (public domain).
- Eurostat, HICP ECOICOP ver.2 (prc_hicp_minr), frei mit Quellenangabe.
SARON ist bewusst nicht enthalten (Index der SIX, Weitergabe lizenzpflichtig).
"""
from __future__ import annotations

import csv
import datetime as dt
import io

import httpx

import sources as src

NYFED = "https://markets.newyorkfed.org/api/rates"
NYFED_NOTICE = ("Rates data © Federal Reserve Bank of New York, subject to the Terms of Use posted at "
                "newyorkfed.org. The New York Fed is not responsible for this republication and has no liability "
                "for its use. This service is not affiliated with, sanctioned, endorsed or recommended by the "
                "New York Fed. SOFR/BGCR are calculated using data licensed from DTCC Solutions LLC.")
ECB_ESTR = "https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT"
BLS = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
RATES = {"SOFR": ("secured", "sofr", "Secured Overnight Financing Rate (USD)"),
         "EFFR": ("unsecured", "effr", "Effective Federal Funds Rate (USD)"),
         "OBFR": ("unsecured", "obfr", "Overnight Bank Funding Rate (USD)"),
         "ESTR": (None, None, "Euro short-term rate €STR (EUR)")}
CPI_SERIES = {"CUUR0000SA0": "headline_nsa", "CUUR0000SA0L1E": "core_nsa",
              "CUSR0000SA0": "headline_sa", "CUSR0000SA0L1E": "core_sa"}
# BLS-Veröffentlichungstermine CPI (08:30 ET), Quelle bls.gov/schedule/news_release/cpi.htm
CPI_DATES = ["2026-11-10", "2026-12-10", "2027-01-13", "2027-02-11", "2027-03-10", "2027-04-13", "2027-05-12",
             "2027-06-10", "2027-07-14", "2027-08-11", "2027-09-14", "2027-10-14", "2027-11-10", "2027-12-10"]
EU_GEOS = {"EA", "EU", "EU27_2020", "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR",
           "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "IS", "NO", "CH", "TR"}


def _http(method: str, url: str, **kw):
    r = httpx.request(method, url, headers={**src.UA, "Accept": kw.pop("accept", "application/json")},
                      timeout=30, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


# ------------------------------------------------------------------ A31
def _nyfed(kind: str, code: str, n: int) -> list[dict]:
    j = _http("GET", f"{NYFED}/{kind}/{code}/last/{n}.json").json()
    out = []
    for r in j.get("refRates", []):
        out.append({"date": r.get("effectiveDate"), "rate_pct": r.get("percentRate"),
                    "percentile_1": r.get("percentPercentile1"), "percentile_25": r.get("percentPercentile25"),
                    "percentile_75": r.get("percentPercentile75"), "percentile_99": r.get("percentPercentile99"),
                    "volume_bn_usd": r.get("volumeInBillions"),
                    "target_range": ([r["targetRateFrom"], r["targetRateTo"]]
                                     if r.get("targetRateFrom") is not None else None),
                    "revised": bool(r.get("revisionIndicator"))})
    return sorted(out, key=lambda x: x["date"] or "")


def _estr(n: int) -> list[dict]:
    text = _http("GET", ECB_ESTR, params={"lastNObservations": n, "format": "csvdata"}, accept="text/csv").text
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        v = r.get("OBS_VALUE")
        if r.get("TIME_PERIOD") and v not in (None, "", "NaN"):
            rows.append({"date": r["TIME_PERIOD"], "rate_pct": round(float(v), 3)})
    return sorted(rows, key=lambda x: x["date"])


def reference_rate(name: str = "SOFR", date: str | None = None, days: int = 1) -> dict:
    k = (name or "SOFR").strip().upper().replace("€", "E")
    k = {"€STR": "ESTR", "STR": "ESTR", "EURSTR": "ESTR", "FEDFUNDS": "EFFR", "FED_FUNDS": "EFFR"}.get(k, k)
    if k == "SARON":
        raise KeyError("SARON is a SIX index and not offered (licensed). Available: SOFR, EFFR, OBFR, ESTR")
    if k not in RATES:
        raise KeyError(f"Unknown rate '{name}'. Available: SOFR, EFFR, OBFR, ESTR")
    if not 1 <= days <= 250:
        raise ValueError("days must be 1-250")
    want = None
    if date:
        try:
            want = dt.date.fromisoformat(date)
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD")
        if want > _today():
            raise ValueError("date is in the future")
    n = max(days, ((_today() - want).days + 5) if want else days)
    if n > 300:
        raise ValueError("date too far back (max. about 300 days)")
    n = 10 if n < 10 else (60 if n <= 60 else 300)
    kind, code, label = RATES[k]
    rows = src.cached(f"rate|{k}|{n}", 3600, (lambda: _estr(n)) if k == "ESTR" else (lambda: _nyfed(kind, code, n)))
    if not rows:
        raise src.SourceUnavailable("No data returned by the source")
    if want:
        upto = [r for r in rows if r["date"] <= want.isoformat()]
        if not upto:
            raise KeyError("No fixing on or before that date in range")
        sel = upto[-days:]
        note = None if sel[-1]["date"] == want.isoformat() else f"No fixing on {want}; latest prior fixing shown."
    else:
        sel, note = rows[-days:], None
    latest = sel[-1]
    prev = rows[rows.index(latest) - 1] if rows.index(latest) > 0 else None
    out = {"rate": k, "name": label, "latest": latest,
           "change_bp_vs_previous": (round((latest["rate_pct"] - prev["rate_pct"]) * 100, 1)
                                     if prev and latest.get("rate_pct") is not None else None),
           "history": sel if days > 1 else None, "note": note,
           "publication": ("Published around 08:00 ET for the previous business day" if k != "ESTR"
                           else "Published at 08:00 CET for the previous TARGET2 business day")}
    if k == "ESTR":
        out["source"] = "European Central Bank, €STR (data-api.ecb.europa.eu). Source: ECB statistics."
    else:
        out["source"] = "Federal Reserve Bank of New York, Reference Rates (markets.newyorkfed.org)"
        out["notice"] = NYFED_NOTICE
    return {k2: v for k2, v in out.items() if v is not None}


# ------------------------------------------------------------------ A38
def _bls() -> dict:
    j = _http("POST", BLS, json={"seriesid": list(CPI_SERIES)}).json()
    if j.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("BLS: " + "; ".join(j.get("message") or ["request failed"])[:150])
    out = {}
    for s in j["Results"]["series"]:
        pts = {}
        for d in s.get("data", []):
            p = d.get("period", "")
            if p.startswith("M") and p != "M13":
                try:
                    pts[f"{d['year']}-{p[1:]}"] = float(d["value"])
                except (KeyError, ValueError):
                    pass
        out[CPI_SERIES[s["seriesID"]]] = pts
    return out


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def _prev_month(ym: str, k: int = 1) -> str:
    y, m = map(int, ym.split("-"))
    m -= k
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


def _us_cpi() -> dict:
    d = src.cached("bls|cpi", 6 * 3600, _bls)
    h, c, hs, cs = d.get("headline_nsa", {}), d.get("core_nsa", {}), d.get("headline_sa", {}), d.get("core_sa", {})
    if not h:
        raise src.SourceUnavailable("BLS returned no CPI data")
    last = max(h)

    def row(ym):
        return {"month": ym, "headline_yoy_pct": _pct(h.get(ym), h.get(_prev_month(ym, 12))),
                "core_yoy_pct": _pct(c.get(ym), c.get(_prev_month(ym, 12))),
                "headline_mom_pct_sa": _pct(hs.get(ym), hs.get(_prev_month(ym))),
                "core_mom_pct_sa": _pct(cs.get(ym), cs.get(_prev_month(ym))),
                "index_nsa": h.get(ym)}
    today = _today().isoformat()
    nxt = next((x for x in CPI_DATES if x >= today), None)
    return {"region": "US", "measure": "CPI-U (all items; core = less food and energy)",
            "latest": row(last), "previous": row(_prev_month(last)),
            "next_release": {"date": nxt, "time": "08:30 ET"} if nxt else None,
            "source": "U.S. Bureau of Labor Statistics, CPI (api.bls.gov), public domain"}


def _eurostat(geo: str) -> dict:
    j = _http("GET", EUROSTAT, params=[("geo", geo), ("coicop18", "TOTAL"), ("unit", "RCH_A"),
                                       ("unit", "RCH_M"), ("lastTimePeriod", "3")]).json()
    ids, size = j.get("id", []), j.get("size", [])
    if not ids or 0 in size:
        raise KeyError(f"No HICP data for '{geo}'")
    dims = j["dimension"]
    units = dims["unit"]["category"]["index"]
    times = dims["time"]["category"]["index"]
    strides, acc = {}, 1
    for name, n in reversed(list(zip(ids, size))):
        strides[name] = acc
        acc *= n
    val = j.get("value", {})

    def get(unit, t):
        pos = units[unit] * strides["unit"] + times[t] * strides["time"]
        return val.get(str(pos))
    rows = [{"month": t, "hicp_yoy_pct": get("RCH_A", t) if "RCH_A" in units else None,
             "hicp_mom_pct": get("RCH_M", t) if "RCH_M" in units else None} for t in sorted(times)]
    rows = [r for r in rows if r["hicp_yoy_pct"] is not None]
    if not rows:
        raise KeyError(f"No HICP data for '{geo}'")
    return {"rows": rows, "updated": j.get("updated")}


def inflation(region: str = "US") -> dict:
    r = (region or "US").strip().upper()
    r = {"USA": "US", "EUROZONE": "EA", "EURO": "EA", "EUROAREA": "EA", "GR": "EL", "UK": "GB"}.get(r, r)
    if r == "US":
        return _us_cpi()
    if r not in EU_GEOS:
        raise KeyError(f"Region '{region}' not supported. Use US, EA (euro area), EU or a European country code")
    geo = "EU27_2020" if r == "EU" else r
    d = src.cached(f"hicp|{geo}", 6 * 3600, lambda: _eurostat(geo))
    rows = d["rows"]
    return {"region": r, "measure": "HICP all items (ECOICOP ver.2), annual and monthly rate of change",
            "latest": rows[-1], "previous": rows[-2] if len(rows) > 1 else None, "dataset_updated": d["updated"],
            "next_release": {"note": "Eurostat publishes the euro-area flash estimate at the end of the month "
                                     "or first working day after, final data mid-month."},
            "source": "Eurostat, HICP (prc_hicp_minr), free re-use with source acknowledgement"}
