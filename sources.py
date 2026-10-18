"""Datenquellen der Macro Data API (alle frei nutzbar).

- US Treasury Daily Par Yield Curve Rates (CC0 / US Government Work)
- EZB Euro-Referenzkurse (frei mit Quellenangabe: "Source: ECB statistics")
- CFTC Commitments of Traders, Legacy Futures Only (US Government Work)

Die Leser sind bewusst tolerant (Spaltennamen und Datumsformate werden erkannt),
weil die Quellen ihr Format gelegentlich leicht ändern. Abrufe werden zwischengespeichert.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx

UA = {"User-Agent": "MarketDataAPIs/0.1 (contact: data-api@users.noreply.github.com)"}
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()
STATUS: dict[str, dict] = {}


def cached(key: str, ttl: int, loader):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    try:
        val = loader()
        with _lock:
            _cache[key] = (now, val)
        STATUS[key] = {"ok": True, "loaded_at": dt.datetime.now(dt.timezone.utc).isoformat()}
        return val
    except Exception as e:  # alte Daten weiterverwenden, falls vorhanden
        STATUS[key] = {"ok": False, "error": str(e)[:200],
                       "at": dt.datetime.now(dt.timezone.utc).isoformat()}
        if hit:
            return hit[1]
        raise SourceUnavailable(f"Data source temporarily unavailable ({key}). Please retry later.")


class SourceUnavailable(RuntimeError):
    pass


def _get(url: str, timeout: float = 30) -> httpx.Response:
    r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r


def parse_date(s: str) -> dt.date:
    s = s.strip().strip('"')
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"unknown date format: {s!r}")


# ------------------------------------------------------------------ Treasury
TENOR_KEYS = {  # normalisierte Laufzeit -> (Monate, Anzeigename)
    "1m": (1, "1 Mo"), "1.5m": (1.5, "1.5 Mo"), "2m": (2, "2 Mo"), "3m": (3, "3 Mo"), "4m": (4, "4 Mo"),
    "6m": (6, "6 Mo"), "1y": (12, "1 Yr"), "2y": (24, "2 Yr"), "3y": (36, "3 Yr"), "5y": (60, "5 Yr"),
    "7y": (84, "7 Yr"), "10y": (120, "10 Yr"), "20y": (240, "20 Yr"), "30y": (360, "30 Yr"),
}


def norm_tenor(label: str) -> str | None:
    m = re.match(r"\s*([\d.]+)\s*(mo|month|months|m|yr|year|years|y)\b", label.strip().lower())
    if not m:
        return None
    n, unit = m.group(1), m.group(2)
    n = n.rstrip("0").rstrip(".") if "." in n else n
    key = f"{n}{'m' if unit.startswith('m') else 'y'}"
    return key if key in TENOR_KEYS else None


def parse_treasury_csv(text: str) -> dict[dt.date, dict[str, float]]:
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    cols = {i: norm_tenor(h) for i, h in enumerate(header)}
    date_i = next(i for i, h in enumerate(header) if h.strip().strip('"').lower() == "date")
    out = {}
    for r in rows[1:]:
        if not r or not r[date_i].strip():
            continue
        d = parse_date(r[date_i])
        vals = {}
        for i, k in cols.items():
            if k and i < len(r) and r[i].strip() not in ("", "N/A"):
                try:
                    vals[k] = float(r[i])
                except ValueError:
                    pass
        if vals:
            out[d] = vals
    return out


def treasury_year(year: int) -> dict[dt.date, dict[str, float]]:
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv")
    ttl = 3600 if year >= dt.date.today().year else 7 * 86400
    return cached(f"treasury:{year}", ttl, lambda: parse_treasury_csv(_get(url).text))


# ------------------------------------------------------------------ EZB
ECB_NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def parse_ecb_xml(text: str) -> dict[dt.date, dict[str, float]]:
    root = ET.fromstring(text)
    out = {}
    for day in root.iter("{%s}Cube" % ECB_NS["e"]):
        t = day.get("time")
        if not t:
            continue
        rates = {c.get("currency"): float(c.get("rate")) for c in day if c.get("currency")}
        rates["EUR"] = 1.0
        out[parse_date(t)] = rates
    return out


def ecb_recent() -> dict[dt.date, dict[str, float]]:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
    return cached("ecb:90d", 1800, lambda: parse_ecb_xml(_get(url).text))


def ecb_full() -> dict[dt.date, dict[str, float]]:
    url = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
    return cached("ecb:hist", 12 * 3600, lambda: parse_ecb_xml(_get(url, 90).text))


# ------------------------------------------------------------------ CFTC COT
COT_MARKETS = {  # Kurzname -> (CFTC-Kontraktcode, Beschreibung)
    "ES": ("13874A", "E-mini S&P 500 (CME)"),
    "NQ": ("209742", "Nasdaq-100 mini (CME)"),
    "YM": ("124603", "Dow Jones mini $5 (CBOT)"),
    "RTY": ("239742", "Russell 2000 mini (CME)"),
    "GC": ("088691", "Gold (COMEX)"),
    "SI": ("084691", "Silver (COMEX)"),
    "CL": ("067651", "Crude oil WTI (NYMEX)"),
    "NG": ("023651", "Natural gas Henry Hub (NYMEX)"),
    "6E": ("099741", "Euro FX (CME)"),
    "6J": ("097741", "Japanese yen (CME)"),
    "6B": ("096742", "British pound (CME)"),
    "6S": ("092741", "Swiss franc (CME)"),
    "ZN": ("043602", "10-year T-note (CBOT)"),
    "BTC": ("133741", "Bitcoin (CME)"),
}
COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


def _field(rec: dict, *parts: str) -> float | None:
    for k, v in rec.items():
        lk = k.lower()
        if all(p in lk for p in parts) and "pct" not in lk and "change" not in lk and "traders" not in lk \
                and "old" not in lk and "other" not in lk:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def parse_cot_records(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        date_key = next((k for k in r if "report_date" in k.lower()), None)
        if not date_key:
            continue
        nc_l, nc_s = _field(r, "noncomm", "long", "all"), _field(r, "noncomm", "short", "all")
        c_l, c_s = _field(r, "comm_positions", "long", "all"), _field(r, "comm_positions", "short", "all")
        # "comm_positions" passt auch auf "noncomm_positions" -> exakt filtern
        c_l = next((float(v) for k, v in r.items() if k.lower().startswith("comm_positions_long_all")), c_l)
        c_s = next((float(v) for k, v in r.items() if k.lower().startswith("comm_positions_short_all")), c_s)
        nr_l, nr_s = _field(r, "nonrept", "long", "all"), _field(r, "nonrept", "short", "all")
        oi = _field(r, "open_interest", "all")
        out.append({"report_date": parse_date(r[date_key]).isoformat(),
                    "market": r.get("market_and_exchange_names", ""),
                    "open_interest": oi,
                    "noncommercial": {"long": nc_l, "short": nc_s,
                                      "net": None if nc_l is None or nc_s is None else nc_l - nc_s},
                    "commercial": {"long": c_l, "short": c_s,
                                   "net": None if c_l is None or c_s is None else c_l - c_s},
                    "nonreportable": {"long": nr_l, "short": nr_s,
                                      "net": None if nr_l is None or nr_s is None else nr_l - nr_s}})
    out.sort(key=lambda x: x["report_date"], reverse=True)
    return out


def cot_history(code: str, weeks: int = 52) -> list[dict]:
    def load():
        r = httpx.get(COT_URL, headers=UA, timeout=30, params={
            "cftc_contract_market_code": code, "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": "260"})
        r.raise_for_status()
        recs = parse_cot_records(r.json())
        if not recs:
            raise ValueError("no COT records returned")
        return recs
    return cached(f"cot:{code}", 6 * 3600, load)[:weeks]


def status() -> dict:
    return STATUS
