"""Live NAV for Nordnet-style fund holdings, via Yahoo Finance.

Nordnet's own CSV export (see import_portfolio.py) has no live API — its
"market value" is a snapshot frozen at the moment the CSV was downloaded, and
funds like "KLP AksjeUSA Indeks N" or "Nordnet One Offensiv NOK" are Nordnet's
internal fund names, not exchange tickers, so yfinance's normal
resolve-a-ticker path (data_sources/stocks.py) never finds them.

Yahoo Finance turns out to carry these same funds under Morningstar-style
mutual-fund symbols (e.g. "KLP AksjeUSA Indeks N" -> "0P0001OPC2.IR", priced
in NOK). This module resolves a Nordnet fund name to that symbol via Yahoo's
search endpoint, then reuses yfinance for daily NAV history — same pattern as
stocks.resolve_symbol, just searched by name instead of probing suffixes.
"""

from functools import lru_cache

import pandas as pd
import requests
import yfinance as yf

_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"


@lru_cache(maxsize=64)
def resolve_symbol(fund_name: str) -> str | None:
    """Find the Yahoo mutual-fund symbol matching a Nordnet fund name. Cached per
    process so repeated dashboard polls don't re-search Yahoo every time."""
    try:
        resp = requests.get(
            _SEARCH_URL,
            params={"q": fund_name, "quotesCount": 5, "newsCount": 0},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])
    except (requests.exceptions.RequestException, ValueError):
        return None

    funds = [q for q in quotes if q.get("quoteType") == "MUTUALFUND"]
    if not funds:
        return None

    # Prefer an exact name match; Yahoo sometimes ranks a similarly-named fund
    # from another provider above the right one.
    for q in funds:
        if (q.get("longname") or q.get("shortname") or "").strip().lower() == fund_name.strip().lower():
            return q["symbol"]
    return funds[0]["symbol"]


def get_price_history(fund_name: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Returns a DataFrame indexed by date with a Close column of daily NOK NAV."""
    resolved = resolve_symbol(fund_name)
    if resolved is None:
        return pd.DataFrame()
    hist = yf.Ticker(resolved).history(period=period, interval=interval)
    return hist.dropna(subset=["Close"]) if not hist.empty else hist


def get_latest_price(fund_name: str) -> float | None:
    hist = get_price_history(fund_name, period="5d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])
