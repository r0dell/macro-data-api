# Macro Data API (v0.1)

Öffentliche Makrodaten für KI-Agenten, bezahlt pro Abfrage über x402 (USDC auf Base).

| Endpunkt | Liefert | Preis |
|---|---|---|
| `/v1/yield-curve?date=` | US-Treasury-Zinskurve 1M–30J, Spreads 2J–10J und 3M–10J, Kurvenform | 0.01 USDC |
| `/v1/spread?a=2y&b=10y` | Spread zweier Laufzeiten, invers ja/nein | 0.01 USDC |
| `/v1/fx?base=EUR&quote=USD` | EZB-Referenzkurs inkl. Kreuzkurse (z. B. CHF/USD) | 0.011 USDC |
| `/v1/convert?amount=100&from=CHF&to=USD` | Umrechnung mit EZB-Referenzkursen | 0.011 USDC |
| `/v1/cot?market=ES&weeks=1` | CFTC Commitments of Traders: Netto-Positionen, Wochenänderung, Historie | 0.02 USDC |
| `/v1/cot-markets`, `/v1/sources`, `/docs` | Marktliste, Quellenstatus, Doku | gratis |

Quellen: U.S. Treasury (public domain), «Source: ECB statistics» (frei mit Quellenangabe, unverändert),
CFTC (public domain). Abrufe werden zwischengespeichert. Tests: `python -m pytest -q`.
