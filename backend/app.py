"""Entry point. Run with: uvicorn app:app --reload
Serves the API under /api/* and the static frontend at /.
"""

import ca_bundle  # noqa: F401 — must run before anything makes an HTTPS call

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import backtest as backtest_module
import db
import recommend as recommend_module
from data_sources import crypto_firi, fundamentals, funds, fx, stocks
from signals import evaluate_all

app = FastAPI(title="Investment Portfolio App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool for now; tighten if this ever leaves localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    db.init_db()


class HoldingIn(BaseModel):
    symbol: str
    asset_type: Literal["stock", "crypto"]
    quantity: float
    avg_price: float


class WatchlistIn(BaseModel):
    symbol: str
    asset_type: Literal["stock", "crypto"]
    note: str = ""


def _price_history(symbol: str, asset_type: str):
    if asset_type == "stock":
        return stocks.get_price_history(symbol)
    if asset_type == "crypto":
        return crypto_firi.get_daily_close_history(symbol)
    raise HTTPException(400, "asset_type must be 'stock' or 'crypto'")


@app.get("/api/signals/{symbol}")
def get_signals(symbol: str, asset_type: Literal["stock", "crypto"] = "stock"):
    df = _price_history(symbol, asset_type)
    if df is None or df.empty:
        raise HTTPException(404, f"no price data for {symbol}")

    results = evaluate_all(df)
    return {
        "symbol": symbol.upper(),
        "asset_type": asset_type,
        "latest_price": float(df["Close"].iloc[-1]),
        "signals": [asdict(r) for r in results],
    }


@app.get("/api/holdings")
def get_holdings():
    return db.list_holdings()


@app.post("/api/holdings")
def create_holding(holding: HoldingIn):
    holding_id = db.add_holding(holding.symbol, holding.asset_type, holding.quantity, holding.avg_price)
    return {"id": holding_id}


@app.delete("/api/holdings/{holding_id}")
def delete_holding(holding_id: int):
    db.remove_holding(holding_id)
    return {"ok": True}


@app.get("/api/watchlist")
def get_watchlist():
    return db.list_watchlist()


@app.post("/api/watchlist")
def create_watchlist_entry(entry: WatchlistIn):
    entry_id = db.add_watchlist(entry.symbol, entry.asset_type, entry.note)
    return {"id": entry_id}


@app.delete("/api/watchlist/{entry_id}")
def delete_watchlist_entry(entry_id: int):
    db.remove_watchlist(entry_id)
    return {"ok": True}


def _fund_signals(symbol: str) -> dict | None:
    """Live NAV + signals for a Nordnet fund via Yahoo Finance (see data_sources/funds.py).
    Returns None if Yahoo has no matching fund or the lookup fails."""
    df = funds.get_price_history(symbol)
    if df is None or df.empty:
        return None
    return {
        "latest_price": float(df["Close"].iloc[-1]),
        "signals": [asdict(r) for r in evaluate_all(df)],
    }


@app.get("/api/dashboard")
def dashboard():
    """One call for the frontend: holdings + watchlist, each enriched with current signals."""

    def enrich(item: dict) -> dict:
        # Nordnet fund symbols are full fund names ("KLP AksjeUSA Indeks N"), not
        # tickers, so they don't resolve on stocks.py's ticker-probing path. Yahoo
        # Finance carries them separately under Morningstar-style fund symbols
        # (data_sources/funds.py) — try that first, since it gives a real live price
        # to compare against avg_price (GAV) instead of a possibly stale import.
        if item.get("category") == "fund":
            live = _fund_signals(item["symbol"])
            if live:
                return {**item, **live, "note": "live NAV from Yahoo Finance"}

            price = item.get("avg_price")
            note = "no live price available — showing average buy price (GAV); gain/loss not reflected"
            if item.get("nordnet_market_value") and item.get("quantity"):
                price = item["nordnet_market_value"] / item["quantity"]
                note = "live price unavailable — using last known Nordnet value from import"
            return {**item, "latest_price": price, "signals": [], "note": note}
        try:
            return {**item, **get_signals(item["symbol"], item["asset_type"])}
        except Exception as exc:  # keep one bad symbol from breaking the whole dashboard
            return {**item, "error": str(exc)}

    return {
        "holdings": [enrich(h) for h in db.list_holdings()],
        "watchlist": [enrich(w) for w in db.list_watchlist()],
    }


@app.get("/api/allocation")
def get_allocation():
    """Portfolio breakdown by category (stocks, funds) with percentages and total value."""
    holdings = db.list_holdings()
    
    if not holdings:
        return {
            "total_value_nok": 0,
            "categories": {},
            "by_category": {"stock": {"count": 0, "value": 0, "percent": 0}, "fund": {"count": 0, "value": 0, "percent": 0}},
        }
    
    # Enrich with current prices or use Nordnet values
    enriched = []
    for h in holdings:
        # Funds: Nordnet's own export has no live API (nordnet_market_value is a
        # snapshot frozen at import time), and its fund names aren't stock tickers,
        # so get_signals()/yfinance can't price them either. Get a real live price
        # from Yahoo's fund data instead (data_sources/funds.py) and compare that
        # to avg_price (GAV), falling back to the stale Nordnet snapshot and then
        # GAV itself only if Yahoo has no match.
        if h.get("category") == "fund":
            live_price = funds.get_latest_price(h["symbol"])
            if live_price:
                value = h["quantity"] * live_price
                enriched.append({**h, "current_price": live_price, "value": value, "source": "live-fund"})
            elif h.get("nordnet_market_value") and h["nordnet_market_value"] > 0:
                value = h["nordnet_market_value"]
                enriched.append({**h, "current_price": value / h["quantity"], "value": value, "source": "nordnet"})
            else:
                value = h["quantity"] * h["avg_price"]
                enriched.append({**h, "current_price": h["avg_price"], "value": value, "source": "avg"})
            continue

        # Prefer Nordnet market value if available, otherwise fetch current price
        if h.get("nordnet_market_value") and h["nordnet_market_value"] > 0:
            value = h["nordnet_market_value"]
            enriched.append({**h, "current_price": value / h["quantity"], "value": value, "source": "nordnet"})
        else:
            try:
                signals_data = get_signals(h["symbol"], h["asset_type"])
                price = signals_data.get("latest_price", h["avg_price"])
                value = h["quantity"] * price
                enriched.append({**h, "current_price": price, "value": value, "source": "live"})
            except Exception:
                value = h["quantity"] * h["avg_price"]
                enriched.append({**h, "current_price": h["avg_price"], "value": value, "source": "avg"})
    
    # Calculate values by category
    by_category = {}
    total_value = 0
    
    for holding in enriched:
        category = holding.get("category", "stock")
        value = holding["value"]
        total_value += value
        
        if category not in by_category:
            by_category[category] = {"count": 0, "value": 0, "items": []}
        
        by_category[category]["count"] += 1
        by_category[category]["value"] += value
        by_category[category]["items"].append({
            "symbol": holding["symbol"],
            "quantity": holding["quantity"],
            "price": holding["current_price"],
            "value": value,
            "unrealized_gain": value - (holding["quantity"] * holding["avg_price"]),
            "source": holding.get("source", "unknown"),
        })
    
    # Calculate percentages
    for category in by_category:
        by_category[category]["percent"] = (by_category[category]["value"] / total_value * 100) if total_value > 0 else 0

    # One row per day, overwritten on every call — this is how /api/portfolio-history
    # builds up over time, with no separate cron/scheduler needed for a local single-user app.
    category_values = {cat: round(info["value"], 2) for cat, info in by_category.items()}
    db.save_snapshot(str(date.today()), round(total_value, 2), json.dumps(category_values))

    return {
        "total_value_nok": round(total_value, 2),
        "by_category": by_category,
        "note": "Funds use live NAV from Yahoo Finance when available (falling back to the last Nordnet import, then GAV); other holdings prefer the last Nordnet import, falling back to live prices",
    }


@app.get("/api/portfolio-history")
def get_portfolio_history(days: int = 365):
    """Total portfolio value over time — built up one row per day from /api/allocation
    calls (see db.save_snapshot). Empty/thin until the app's been used for a while;
    there's no backfill for days before this feature existed."""
    snapshots = db.get_snapshots(days)
    return {
        "days": days,
        "points": [
            {
                "date": s["date"],
                "total_value_nok": s["total_value_nok"],
                "by_category": json.loads(s["by_category_json"]),
            }
            for s in snapshots
        ],
    }


def _period_for_days(days: int) -> str:
    if days <= 30:
        return "1mo"
    if days <= 90:
        return "3mo"
    if days <= 180:
        return "6mo"
    if days <= 365:
        return "1y"
    return "2y"


@app.get("/api/performance")
def get_performance(category: Literal["stock", "fund", "crypto"] = "stock", days: int = 365):
    """Normalized % change since the start of the window, per holding in a category —
    lets the frontend compare stocks/funds/crypto on one chart despite wildly different
    price scales (a fund NAV of ~200 NOK vs. a crypto price of ~600000 NOK)."""
    holdings = [h for h in db.list_holdings() if h.get("category", "stock") == category]
    period = _period_for_days(days)
    # Everything is stored/computed in NOK (see stocks.py's FX-conversion note), but crypto
    # is more commonly read in USD, so attach a USD-equivalent price alongside NOK for it.
    nok_to_usd = fx.get_rate("NOK", "USD") if category == "crypto" else None

    series = []
    for h in holdings:
        symbol = h["symbol"]
        try:
            if category == "fund":
                df = funds.get_price_history(symbol, period=period)
            elif category == "crypto":
                df = crypto_firi.get_daily_close_history(symbol)
            else:
                df = stocks.get_price_history(symbol, period=period)
        except Exception:  # keep one bad symbol (e.g. a data source's API quirk) from 500ing the whole chart
            continue

        if df is None or df.empty:
            continue

        closes = df["Close"].dropna().tail(days)
        if closes.empty:
            continue

        base = float(closes.iloc[0])
        if base == 0:
            continue

        series.append({
            "symbol": symbol,
            "points": [
                {
                    "date": str(idx.date()),
                    "change_pct": round((float(v) / base - 1) * 100, 2),
                    "price_nok": round(float(v), 2),
                    **({"price_usd": round(float(v) * nok_to_usd, 2)} if nok_to_usd else {}),
                }
                for idx, v in closes.items()
            ],
        })

    return {"category": category, "days": days, "currency": "NOK", "series": series}


@app.get("/api/recommend")
def get_recommendation():
    """Scores every current holding + watchlist symbol for growth potential and returns
    the top pick, with the full ranking for transparency (see recommend.py) — deliberately
    on-demand, not part of the dashboard poll, since it fetches fundamentals for every
    candidate."""
    candidates = db.list_holdings() + db.list_watchlist()
    seen = set()
    unique = []
    for c in candidates:
        if c["symbol"] in seen:
            continue
        seen.add(c["symbol"])
        unique.append(c)
    return recommend_module.recommend(unique)


@app.get("/api/backtest/{symbol}")
def get_backtest(symbol: str, category: Literal["stock", "fund", "crypto"] = "stock", days: int = 365):
    """Replays the confluence signal against this holding's own history and compares it
    to buy-and-hold — see backtest.py. On-demand only (not part of the dashboard poll):
    a full walk-forward backtest re-runs evaluate_all() once per day of history, which is
    too slow to run on every 60s refresh for every holding."""
    period = _period_for_days(days)
    if category == "fund":
        df = funds.get_price_history(symbol, period=period)
    elif category == "crypto":
        df = crypto_firi.get_daily_close_history(symbol)
    else:
        df = stocks.get_price_history(symbol, period=period)

    if df is None or df.empty:
        return {"available": False, "note": "no price history available"}

    return backtest_module.backtest(df.tail(days))


@app.get("/api/fundamentals/{symbol}")
def get_fundamentals(symbol: str, category: Literal["stock", "fund", "crypto"] = "stock"):
    """On-demand detail for one holding — P/E, EPS, analyst target, headlines (stocks/funds
    via yfinance) or market cap/supply/ATH (crypto via CoinGecko). Deliberately NOT part of
    /api/dashboard: this data barely moves intraday, and fetching it for every holding on
    every 60s poll is exactly what rate-limited CoinGecko into breaking BTC's price history."""
    return fundamentals.get_fundamentals(symbol, category)


@app.get("/api/price-history/{symbol}")
def get_price_history_chart(symbol: str, days: int = 365):
    """Get price history for charting. Default: last year."""
    history = db.get_price_history(symbol, min(days, 1825))  # max 5 years
    
    if not history:
        # Fetch current price as fallback
        try:
            df = stocks.get_price_history(symbol)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                return {
                    "symbol": symbol.upper(),
                    "data": [
                        {"date": str(idx.date()), "price": float(val)}
                        for idx, val in zip(df.index, df["Close"])
                    ],
                }
        except:
            pass
        return {"symbol": symbol.upper(), "data": [], "note": "No price history available"}
    
    return {
        "symbol": symbol.upper(),
        "data": history,
    }


frontend_dir = Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
