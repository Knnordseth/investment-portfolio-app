"""Firi (Nordic crypto exchange) REST client. Firi isn't supported by ccxt, so this talks
to their API directly: https://firi.com/about/trading-api

Market data (ticker, trade history) appears to be public. Balances and orders need an API
key from Firi account settings -> API, passed via the FIRI_API_KEY env var.
"""

import os

import pandas as pd
import requests

from . import crypto_coingecko

BASE_URL = "https://api.firi.com/v2"


def _headers() -> dict:
    api_key = os.getenv("FIRI_API_KEY")
    return {"firi-access-key": api_key} if api_key else {}


def get_ticker(market: str) -> dict:
    """market example: 'BTCNOK'"""
    resp = requests.get(f"{BASE_URL}/markets/{market}/ticker", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def _market_for(symbol: str) -> str:
    symbol = symbol.upper()
    return symbol if symbol.endswith("NOK") else f"{symbol}NOK"


def get_trade_history(market: str, count: int = 1000) -> list[dict]:
    resp = requests.get(
        f"{BASE_URL}/markets/{market}/history", params={"count": count}, headers=_headers(), timeout=10
    )
    resp.raise_for_status()
    return resp.json()


def get_balances() -> list[dict]:
    if not os.getenv("FIRI_API_KEY"):
        raise RuntimeError("FIRI_API_KEY not set — required for the private /balances endpoint")
    resp = requests.get(f"{BASE_URL}/balances", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def trade_history_to_daily_closes(trades: list[dict]) -> pd.DataFrame:
    """Firi's /history endpoint returns individual trade fills, not OHLC candles.
    Resample into a daily-close series so the same signal functions used for stocks
    work here too. Verified against a live response: each fill has "created_at" (ISO
    8601 string, not "timestamp"/unix seconds) and "price".
    """
    df = pd.DataFrame(trades)
    if df.empty or "created_at" not in df.columns or "price" not in df.columns:
        return pd.DataFrame()
    df["time"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True).dt.tz_localize(None)
    df = df.dropna(subset=["time"]).set_index("time").sort_index()
    daily = df["price"].astype(float).resample("1D").last().ffill()
    return daily.to_frame(name="Close")


def get_daily_close_history(symbol: str) -> pd.DataFrame:
    """Daily close series for a crypto symbol, suitable for RSI/MA signals.

    Historical closes come from CoinGecko (real daily granularity, months of history).
    Today's row is overlaid with Firi's live bid/ask midpoint so the displayed price
    and MA/RSI calculation reflect the current market, not CoinGecko's last close
    (which can lag by up to a day). Falls back to Firi's own short trade window for
    any symbol CoinGecko isn't mapped for (see crypto_coingecko.SYMBOL_TO_COINGECKO_ID).
    """
    market = _market_for(symbol)
    history = crypto_coingecko.get_daily_closes(symbol)

    if history.empty:
        trades = get_trade_history(market)
        return trade_history_to_daily_closes(trades)

    try:
        ticker = get_ticker(market)
        bid, ask = float(ticker.get("bid") or 0), float(ticker.get("ask") or 0)
        live_price = (bid + ask) / 2 if bid and ask else (bid or ask)
    except (requests.exceptions.RequestException, ValueError):
        live_price = 0

    if live_price:
        history.loc[pd.Timestamp.now().normalize(), "Close"] = live_price
        history = history.sort_index()

    return history
