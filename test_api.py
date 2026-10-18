"""Tests der Macro Data API mit nachgebildeten Quelldaten. Start: python -m pytest -q"""
import types

import pytest
from fastapi.testclient import TestClient

import sources as src
from app import app

TREASURY = '''Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
10/16/2026,4.10,4.08,4.05,4.00,3.95,3.90,3.80,3.60,3.55,3.60,3.70,3.85,4.20,4.30
10/15/2026,4.12,4.09,4.06,4.01,3.96,3.91,3.82,3.95,3.70,3.66,3.72,3.88,4.22,4.31
'''
ECB = '''<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<gesmes:subject>Reference rates</gesmes:subject>
<Cube>
<Cube time="2026-10-16"><Cube currency="USD" rate="1.0800"/><Cube currency="CHF" rate="0.9400"/><Cube currency="JPY" rate="162.00"/></Cube>
<Cube time="2026-10-15"><Cube currency="USD" rate="1.0750"/><Cube currency="CHF" rate="0.9420"/><Cube currency="JPY" rate="161.50"/></Cube>
</Cube></gesmes:Envelope>'''
COT = [
    {"market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
     "report_date_as_yyyy_mm_dd": "2026-10-13T00:00:00.000", "cftc_contract_market_code": "13874A",
     "open_interest_all": "2100000", "noncomm_positions_long_all": "350000", "noncomm_positions_short_all": "420000",
     "noncomm_postions_spread_all": "10000", "comm_positions_long_all": "1500000", "comm_positions_short_all": "1400000",
     "nonrept_positions_long_all": "240000", "nonrept_positions_short_all": "270000",
     "change_in_noncomm_long_all": "5000", "pct_of_oi_noncomm_long_all": "16.7"},
    {"market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
     "report_date_as_yyyy_mm_dd": "2026-10-06T00:00:00.000", "cftc_contract_market_code": "13874A",
     "open_interest_all": "2050000", "noncomm_positions_long_all": "340000", "noncomm_positions_short_all": "430000",
     "comm_positions_long_all": "1490000", "comm_positions_short_all": "1390000",
     "nonrept_positions_long_all": "230000", "nonrept_positions_short_all": "260000"},
]


class Resp:
    def __init__(self, text=None, js=None):
        self.text, self._js = text, js

    def raise_for_status(self):
        pass

    def json(self):
        return self._js


@pytest.fixture(autouse=True)
def fake_sources(monkeypatch):
    src._cache.clear()

    def fake_get(url, *a, **k):
        if "treasury" in url:
            return Resp(TREASURY if "/2026/" in url else 'Date,"1 Mo"\n')
        if "ecb" in url:
            return Resp(ECB)
        if "cftc" in url:
            return Resp(js=COT)
        raise AssertionError(url)
    monkeypatch.setattr(src, "_get", lambda url, timeout=30: fake_get(url))
    monkeypatch.setattr(src.httpx, "get", fake_get)


c = TestClient(app)


def get(path, **params):
    r = c.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_yield_curve_shape_and_spread():
    r = get("/v1/yield-curve", date="2026-10-16")
    assert r["date"] == "2026-10-16"
    assert [x["tenor"] for x in r["curve"]][:3] == ["1m", "1.5m", "2m"]
    assert r["spread_2y_10y"] == 0.25 and r["shape"] == "normal"


def test_yield_curve_uses_previous_day_on_weekend():
    assert get("/v1/yield-curve", date="2026-10-18")["date"] == "2026-10-16"


def test_spread_inverted():
    r = get("/v1/spread", a="2y", b="10y", date="2026-10-15")
    assert r["spread_b_minus_a"] == -0.07 and r["inverted"]


def test_fx_direct_and_cross():
    assert get("/v1/fx", base="EUR", quote="USD")["rate"] == 1.08
    r = get("/v1/fx", base="CHF", quote="USD", date="2026-10-16")
    assert abs(r["rate"] - 1.08 / 0.94) < 1e-6 and "Cross" in r["note"]


def test_convert():
    r = c.get("/v1/convert", params={"amount": 100, "from": "EUR", "to": "JPY"}).json()
    assert r["converted"] == 16200.0


def test_cot_latest_and_change():
    r = get("/v1/cot", market="ES")
    assert r["latest"]["report_date"] == "2026-10-13"
    assert r["latest"]["noncommercial"]["net"] == -70000
    assert r["latest"]["commercial"]["net"] == 100000
    assert r["noncommercial_net_change_vs_prior_week"] == 20000


def test_cot_history():
    assert len(get("/v1/cot", market="ES", weeks=2)["history"]) == 2


def test_errors():
    assert c.get("/v1/cot", params={"market": "XXX"}).status_code == 404
    assert c.get("/v1/fx", params={"quote": "ABC"}).status_code == 400
    assert c.get("/v1/spread", params={"a": "9y"}).status_code == 400


def test_sources_status_free():
    get("/v1/fx", quote="USD")
    assert get("/v1/sources")["status"]["ecb:90d"]["ok"] is True
    r = get("/v1/sources", check="true")
    assert r["latest_dates"]["ecb"] == "2026-10-16" and r["latest_dates"]["cot_ES"] == "2026-10-13"
