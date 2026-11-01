# Macro Data API (v0.1)

Öffentliche Makrodaten für KI-Agenten, bezahlt pro Abfrage über x402 (USDC auf Base).

| Endpunkt | Liefert | Preis |
|---|---|---|
| `/v1/yield-curve?date=` | US-Treasury-Zinskurve 1M–30J, Spreads 2J–10J und 3M–10J, Kurvenform | 0.0205 USDC |
| `/v1/spread?a=2y&b=10y` | Spread zweier Laufzeiten, invers ja/nein | 0.0205 USDC |
| `/v1/fx?base=EUR&quote=USD` | EZB-Referenzkurs inkl. Kreuzkurse (z. B. CHF/USD) | 0.0225 USDC |
| `/v1/convert?amount=100&from=CHF&to=USD` | Umrechnung mit EZB-Referenzkursen | 0.0225 USDC |
| `/v1/cot?market=ES&weeks=1` | CFTC Commitments of Traders: Netto-Positionen, Wochenänderung, Historie | 0.0405 USDC |
| `/v1/reference-rate?name=SOFR` | SOFR, EFFR, OBFR (NY Fed) oder €STR (EZB): letzter oder datierter Wert, Historie | 0.0305 USDC |
| `/v1/inflation?region=US` | US-CPI (Gesamt/Kern, J/J und M/M) mit nächstem Termin, oder HICP Eurozone/EU/Länder | 0.0345 USDC |
| `/v1/cot-markets`, `/v1/sources`, `/docs` | Marktliste, Quellenstatus, Doku | gratis |

Quellen: U.S. Treasury (public domain), «Source: ECB statistics» (frei mit Quellenangabe, unverändert),
CFTC (public domain). Abrufe werden zwischengespeichert. Tests: `python -m pytest -q`.

Zusatzquellen (A31/A38): NY Fed Reference Rates (Terms of Use, Hinweis in jeder Antwort), EZB €STR, BLS CPI (public domain), Eurostat HICP (frei mit Quellenangabe). SARON nicht enthalten (SIX-Lizenz).
