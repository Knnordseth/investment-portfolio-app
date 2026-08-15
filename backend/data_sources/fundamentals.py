"""On-demand fundamentals + headlines for a holding — P/E-style context, not price.

Fetched only when a holding is expanded in the UI (not on the 60s dashboard poll —
see crypto_coingecko.py's rate-limit story for why hammering a free API on every poll
is a bad idea). Cached in-memory for a few hours since this data barely moves intraday.
"""

import time

import requests
import yfinance as yf

from . import crypto_coingecko, funds, stocks

_CACHE_TTL_SECONDS = 6 * 3600
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


def _cached(category: str, symbol: str, fetch):
    key = (category, symbol.upper())
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    result = fetch()
    if result.get("available"):
        _cache[key] = (time.time(), result)
    elif cached:
        return cached[1]  # serve stale data rather than a bare "unavailable"
    return result


def _stock_or_fund_fundamentals(symbol: str, category: str) -> dict:
    resolved = funds.resolve_symbol(symbol) if category == "fund" else stocks.resolve_symbol(symbol)
    if resolved is None:
        return {"available": False, "note": "no matching Yahoo Finance symbol"}

    try:
        ticker = yf.Ticker(resolved)
        info = ticker.info
    except Exception:
        return {"available": False, "note": "fundamentals lookup failed"}

    if not info:
        return {"available": False, "note": "no fundamentals data returned"}

    headlines = []
    try:
        for item in (ticker.news or [])[:3]:
            content = item.get("content", item)
            headlines.append({
                "title": content.get("title"),
                "publisher": (content.get("provider") or {}).get("displayName"),
                "url": (content.get("canonicalUrl") or {}).get("url"),
                "published": content.get("pubDate"),
            })
    except Exception:
        pass

    return {
        "available": True,
        "resolved_symbol": resolved,
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry") or info.get("category"),  # "category" is yfinance's field for funds
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "eps": info.get("trailingEps"),
        "dividend_yield_pct": info.get("dividendYield"),
        "market_cap": info.get("marketCap") or info.get("totalAssets"),  # totalAssets for funds
        "analyst_target_mean": info.get("targetMeanPrice"),
        "analyst_recommendation": info.get("recommendationKey"),
        "week52_high": info.get("fiftyTwoWeekHigh"),
        "week52_low": info.get("fiftyTwoWeekLow"),
        "summary": info.get("longBusinessSummary"),
        "headlines": headlines,
    }


def _crypto_fundamentals(symbol: str) -> dict:
    coin_id = crypto_coingecko.SYMBOL_TO_COINGECKO_ID.get(symbol.upper())
    if coin_id is None:
        return {"available": False, "note": "no matching CoinGecko coin id"}

    try:
        resp = requests.get(
            f"{crypto_coingecko.BASE_URL}/coins/{coin_id}",
            params={
                "localization": "false", "tickers": "false",
                "market_data": "true", "community_data": "false", "developer_data": "false",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return {"available": False, "note": "CoinGecko unavailable (likely rate-limited) — try again shortly"}

    md = data.get("market_data") or {}
    return {
        "available": True,
        "name": data.get("name"),
        "market_cap_rank": data.get("market_cap_rank"),
        "market_cap": (md.get("market_cap") or {}).get("nok"),
        "circulating_supply": md.get("circulating_supply"),
        "total_supply": md.get("total_supply"),
        "ath": (md.get("ath") or {}).get("nok"),
        "ath_change_pct": (md.get("ath_change_percentage") or {}).get("nok"),
        "atl": (md.get("atl") or {}).get("nok"),
        "change_24h_pct": md.get("price_change_percentage_24h"),
        "change_7d_pct": md.get("price_change_percentage_7d"),
        "change_30d_pct": md.get("price_change_percentage_30d"),
        "summary": (data.get("description") or {}).get("en", "")[:600] or None,
        "headlines": [],
    }


def get_fundamentals(symbol: str, category: str) -> dict:
    if category == "crypto":
        return _cached("crypto", symbol, lambda: _crypto_fundamentals(symbol))
    return _cached(category, symbol, lambda: _stock_or_fund_fundamentals(symbol, category))
