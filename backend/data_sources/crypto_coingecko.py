"""Free, no-key daily crypto price history via CoinGecko's public API.

Firi's own /history endpoint only returns a short recent window of raw trade fills
(not OHLC candles) — for a liquid pair like BTCNOK, ~1000 trades covers barely a day,
nowhere near enough for a 50-day MA signal. CoinGecko gives real daily closes going
back months, so it's the primary source for signal history; Firi is still used for the
live bid/ask price (see crypto_firi.get_daily_close_history).
"""

import time

import pandas as pd
import requests

import db

BASE_URL = "https://api.coingecko.com/api/v3"

# CoinGecko's free tier rate-limits hard (~429s) once a handful of coins are each
# fetching months of daily history on every 60s dashboard/performance poll. Daily-close
# data doesn't change intra-minute anyway, so cache each (symbol, days) response for an
# hour — this is what was causing BTC to silently fall back to Firi's ~3-trade window
# and show a near-flat, meaningless price range.
_CACHE_TTL_SECONDS = 3600
_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}

# CoinGecko keys history by its own coin id, not the exchange ticker. Add an entry here
# whenever a new coin is added to holdings/watchlist.
SYMBOL_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "BNB": "binancecoin",
    "DOGE": "dogecoin",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "XLM": "stellar",
    "XRP": "ripple",
}


def get_current_price(symbol: str, vs_currency: str = "nok") -> float | None:
    """Latest price for a symbol via CoinGecko's simple-price endpoint. Used as a
    fallback when Firi doesn't have a market for the coin at all — e.g. AVAX, DOGE,
    LINK and XLM aren't listed on Firi, so its ticker/balance endpoints return
    nothing for them and the import scripts would otherwise store price/value as 0.
    """
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if coin_id is None:
        return None

    try:
        resp = requests.get(
            f"{BASE_URL}/simple/price",
            params={"ids": coin_id, "vs_currencies": vs_currency},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get(coin_id, {}).get(vs_currency)
    except requests.exceptions.RequestException:
        return None


def get_daily_closes(symbol: str, vs_currency: str = "nok", days: int = 365) -> pd.DataFrame:
    """Daily close series for a crypto symbol. Empty DataFrame if the symbol has no
    known CoinGecko id or the API call fails."""
    coin_id = SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if coin_id is None:
        return pd.DataFrame()

    cache_key = (symbol.upper(), vs_currency, days)
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        resp = requests.get(
            f"{BASE_URL}/coins/{coin_id}/market_chart",
            params={"vs_currency": vs_currency, "days": days, "interval": "daily"},
            timeout=10,
        )
        resp.raise_for_status()
        prices = resp.json().get("prices", [])
    except requests.exceptions.RequestException:
        # A stale in-memory cache entry (even expired) beats nothing; failing that, fall
        # back to whatever we last persisted to disk — covers a 429 that outlives a
        # server restart, which is otherwise indistinguishable from "no data at all".
        return cached[1] if cached else _from_db(symbol, days)

    if not prices:
        return cached[1] if cached else _from_db(symbol, days)

    df = pd.DataFrame(prices, columns=["ms", "Close"])
    df["time"] = pd.to_datetime(df["ms"], unit="ms").dt.floor("D")
    df = df.drop_duplicates(subset="time", keep="last").set_index("time").sort_index()
    df = df[["Close"]]
    _cache[cache_key] = (time.time(), df)

    for row in df.reset_index().itertuples(index=False):
        db.save_price_history(f"COINGECKO:{symbol.upper()}", str(row.time.date()), float(row.Close))

    return df


def _from_db(symbol: str, days: int) -> pd.DataFrame:
    rows = db.get_price_history(f"COINGECKO:{symbol.upper()}", days)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["date"])
    return df.set_index("time")[["price"]].rename(columns={"price": "Close"})
