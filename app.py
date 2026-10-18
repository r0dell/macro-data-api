"""HTTP-API: Macro Data API (US-Zinskurve, EZB-Referenzkurse, CFTC COT)."""
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

import macro
import sources as src

app = FastAPI(
    title="Macro Data API",
    version="0.1.0",
    description=("US Treasury par yield curve with 2s10s spread and curve shape, ECB euro reference rates with "
                 "cross rates and conversion, and CFTC Commitments of Traders positioning for index, metal, "
                 "energy, currency and bond futures. Public data, every response names its source."),
)


def _run(fn, *args):
    try:
        return fn(*args)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'\""))
    except src.SourceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/v1/yield-curve", summary="US Treasury par yield curve on a date (default: latest)")
def yield_curve(date: Optional[str] = Query(None, examples=["2026-10-16"])):
    return _run(macro.yield_curve, date)


@app.get("/v1/spread", summary="Spread between two Treasury tenors")
def spread(a: str = Query("2y"), b: str = Query("10y"), date: Optional[str] = None):
    return _run(macro.spread, a, b, date)


@app.get("/v1/fx", summary="ECB reference rate between two currencies (cross rates supported)")
def fx(base: str = Query("EUR"), quote: str = Query(..., examples=["USD"]), date: Optional[str] = None):
    return _run(macro.fx_rate, base, quote, date)


@app.get("/v1/convert", summary="Convert an amount with ECB reference rates")
def convert(amount: float = Query(..., examples=[100]), frm: str = Query(..., alias="from", examples=["CHF"]),
            to: str = Query(..., examples=["USD"]), date: Optional[str] = None):
    return _run(macro.convert, amount, frm, to, date)


@app.get("/v1/cot", summary="CFTC Commitments of Traders positioning for a futures market")
def cot(market: str = Query(..., examples=["ES"]), weeks: int = Query(1, ge=1, le=260)):
    return _run(macro.cot, market, weeks)


@app.get("/v1/cot-markets", summary="Markets available for /v1/cot (free)")
def cot_markets():
    return macro.cot_markets()


@app.get("/v1/sources", summary="Data source status (free)")
def sources_status(check: bool = False):
    """Mit check=true werden alle Quellen einmal geladen (Ergebnis wird zwischengespeichert)."""
    latest = {}
    if check:
        import datetime as dt
        for name, fn in [("treasury", lambda: max(src.treasury_year(dt.date.today().year))),
                         ("ecb", lambda: max(src.ecb_recent())),
                         ("cot_ES", lambda: src.cot_history("13874A", 1)[0]["report_date"])]:
            try:
                latest[name] = str(fn())
            except Exception as e:
                latest[name] = f"error: {e}"[:200]
    return {"latest_dates": latest, "status": src.status()}


@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}
