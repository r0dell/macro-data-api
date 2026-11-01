"""Macro Data API mit x402-Bezahlung (USDC auf Base).

Umgebungsvariablen:
  PAY_TO              Deine Wallet-Adresse (0x...), hierhin gehen die Zahlungen. Pflicht.
  X402_NETWORK        "testnet" (Base Sepolia, Standard) oder "mainnet" (Base).
  CDP_API_KEY_ID      Coinbase-Developer-Platform-Key. Für mainnet und Bazaar-Listing nötig.
  CDP_API_KEY_SECRET  dazugehöriges Secret.
  PUBLIC_URL          Öffentliche https-Adresse des Dienstes (für die Bazaar-Beschreibung).

Start:  uvicorn paid_app:app --host 0.0.0.0 --port 8000
Gratis:  /v1/cot-markets, /v1/sources, /health, /docs
Bezahlt: /v1/yield-curve, /v1/spread, /v1/fx, /v1/convert, /v1/cot
"""
import os
import re

from x402 import x402ResourceServer
from x402.extensions.bazaar import (
    OutputConfig,
    bazaar_resource_server_extension,
    declare_discovery_extension,
)
from x402.http import FacilitatorConfig, HTTPFacilitatorClient
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme

from app import app

NETWORKS = {"testnet": "eip155:84532", "mainnet": "eip155:8453"}
TESTNET_FACILITATOR = os.environ.get("FACILITATOR_URL", "https://x402.org/facilitator")

PAY_TO = os.environ.get("PAY_TO", "").strip()
if not re.fullmatch(r"0x[0-9a-fA-F]{40}", PAY_TO):
    raise SystemExit("PAY_TO fehlt oder ist keine gültige Wallet-Adresse (0x + 40 Hex-Zeichen).")

MODE = os.environ.get("X402_NETWORK", "testnet").lower()
if MODE not in NETWORKS:
    raise SystemExit("X402_NETWORK muss 'testnet' oder 'mainnet' sein.")
NETWORK = NETWORKS[MODE]

CDP_ID = os.environ.get("CDP_API_KEY_ID", "").strip().strip('"\'').strip()
CDP_SECRET = os.environ.get("CDP_API_KEY_SECRET", "").strip().strip('"\'').strip()
if "BEGIN" in CDP_SECRET:
    CDP_SECRET = CDP_SECRET.replace("\\n", "\n")  # PEM aus einzeiligem Feld


def _describe_cdp_keys() -> str:
    """Format der Keys beschreiben, ohne Werte preiszugeben."""
    id_kind = ("uuid" if re.fullmatch(r"[0-9a-fA-F-]{36}", CDP_ID)
               else "organizations-path" if CDP_ID.startswith("organizations/") else "other")
    if "BEGIN EC PRIVATE KEY" in CDP_SECRET:
        sec_kind = "ec-pem"
    else:
        try:
            import base64
            sec_kind = f"base64-{len(base64.b64decode(CDP_SECRET, validate=True))}bytes"
        except Exception:
            sec_kind = "unparseable"
    return f"CDP key: id={id_kind} (len {len(CDP_ID)}), secret={sec_kind} (len {len(CDP_SECRET)})"


if CDP_ID and CDP_SECRET:
    from cdp.x402 import create_facilitator_config
    print(_describe_cdp_keys(), flush=True)
    facilitator_cfg = create_facilitator_config(CDP_ID, CDP_SECRET)
elif MODE == "mainnet":
    raise SystemExit("Für mainnet werden CDP_API_KEY_ID und CDP_API_KEY_SECRET benötigt.")
else:
    facilitator_cfg = FacilitatorConfig(url=TESTNET_FACILITATOR)

server = x402ResourceServer(HTTPFacilitatorClient(facilitator_cfg))
server.register(NETWORK, ExactEvmServerScheme())
server.register_extension(bazaar_resource_server_extension)

SVC = "Macro Data API"


def pay(price: str) -> PaymentOption:
    return PaymentOption(scheme="exact", pay_to=PAY_TO, price=price, network=NETWORK)


def route(price, desc, tags, inp, schema, required, example):
    return RouteConfig(
        accepts=pay(price), description=desc, mime_type="application/json", service_name=SVC, tags=tags,
        extensions=declare_discovery_extension(
            input=inp, input_schema={"properties": schema, "required": required},
            output=OutputConfig(example=example)))


S = lambda d: {"type": "string", "description": d}
DATE = S("Optional date YYYY-MM-DD. Default: latest available.")
TENORS = "1m, 1.5m, 2m, 3m, 4m, 6m, 1y, 2y, 3y, 5y, 7y, 10y, 20y, 30y"
COTM = "ES, NQ, YM, RTY, GC, SI, CL, NG, 6E, 6J, 6B, 6S, ZN, BTC"

# Preise je Agent (eindeutig für den Monitor): A6 0.0205, A7 0.0225, A8 0.0405, A31 0.0305, A38 0.0345 USDC
A31, A38 = "$0.0305", "$0.0345"
routes = {
    "GET /v1/yield-curve": route(
        "$0.0205", "Returns the US Treasury par yield curve (1 month to 30 years) for a date, with the 2y-10y and "
                  "3m-10y spreads and whether the curve is normal, flat or inverted.",
        ["finance", "rates", "treasury", "macro"], {"date": "2026-10-16"}, {"date": DATE}, [],
        {"date": "2026-10-16", "curve": [{"tenor": "2y", "yield": 3.6}, {"tenor": "10y", "yield": 3.85}],
         "spread_2y_10y": 0.25, "shape": "normal"}),
    "GET /v1/spread": route(
        "$0.0205", "Returns the spread in percentage points between two US Treasury tenors on a date and whether "
                  "it is inverted.",
        ["finance", "rates", "treasury"], {"a": "2y", "b": "10y"},
        {"a": S("Tenor: " + TENORS), "b": S("Tenor: " + TENORS), "date": DATE}, [],
        {"a": "2y", "b": "10y", "spread_b_minus_a": 0.25, "inverted": False}),
    "GET /v1/fx": route(
        "$0.0225", "Returns the ECB euro reference exchange rate between two currencies for a date, including "
                   "cross rates such as CHF/USD, with source attribution.",
        ["finance", "forex", "exchange-rates", "ecb"], {"base": "EUR", "quote": "USD"},
        {"base": S("ISO currency code, default EUR"), "quote": S("ISO currency code, e.g. USD"), "date": DATE},
        ["quote"], {"date": "2026-10-16", "base": "EUR", "quote": "USD", "rate": 1.08}),
    "GET /v1/convert": route(
        "$0.0225", "Converts an amount between two currencies using ECB euro reference rates for a date.",
        ["finance", "forex", "conversion"], {"amount": "100", "from": "CHF", "to": "USD"},
        {"amount": S("Amount to convert"), "from": S("ISO currency code"), "to": S("ISO currency code"),
         "date": DATE}, ["amount", "from", "to"],
        {"amount": 100, "base": "CHF", "quote": "USD", "rate": 1.1489, "converted": 114.89}),
    "GET /v1/cot": route(
        "$0.0405", "Returns CFTC Commitments of Traders positioning (non-commercial, commercial and small traders: "
                  "long, short, net) for a futures market, with week-over-week change and optional history.",
        ["finance", "futures", "positioning", "cot"], {"market": "ES"},
        {"market": S("Market: " + COTM), "weeks": S("Weeks of history, 1-260. Default 1.")}, ["market"],
        {"market": "ES", "latest": {"report_date": "2026-10-13", "noncommercial": {"net": -70000}},
         "noncommercial_net_change_vs_prior_week": 20000}),
    "GET /v1/reference-rate": route(
        A31, "Returns the latest (or a dated) fixing of the overnight reference rates SOFR, EFFR, OBFR (New York "
             "Fed) or euro short-term rate ESTR (ECB), with percentiles, volume, change in basis points and "
             "optional history of up to 250 days. For treasury, loan pricing and fixed-income agents.",
        ["finance", "rates", "sofr", "estr", "money-market", "fixed-income"], {"name": "SOFR"},
        {"name": S("SOFR, EFFR, OBFR or ESTR"), "date": DATE, "days": S("History length 1-250, default 1")},
        [], {"rate": "SOFR", "latest": {"date": "2026-10-29", "rate_pct": 3.94, "volume_bn_usd": 3145},
             "change_bp_vs_previous": 0.0}),
    "GET /v1/inflation": route(
        A38, "Latest inflation figures: US CPI-U headline and core (year-over-year and seasonally adjusted "
             "month-over-month) with the next BLS release date, or HICP annual and monthly rates for the euro "
             "area, the EU or a European country (Eurostat).",
        ["finance", "macro", "inflation", "cpi", "hicp", "economics"], {"region": "US"},
        {"region": S("US, EA (euro area), EU or a European country code like DE, FR, CH")}, [],
        {"region": "US", "latest": {"month": "2026-09", "headline_yoy_pct": 2.9, "core_yoy_pct": 3.0,
                                    "headline_mom_pct_sa": 0.2}, "next_release": {"date": "2026-11-10",
                                                                                  "time": "08:30 ET"}}),
}

app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
app.title = f"Macro Data API ({MODE})"
