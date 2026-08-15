"""Cached FX rates via yfinance's FX tickers (e.g. "USDNOK=X")."""

import time

import yfinance as yf

_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[float, float]] = {}


def get_rate(base: str, quote: str) -> float | None:
    """1 unit of `base` expressed in `quote`, e.g. get_rate("NOK", "USD") -> ~0.095."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return 1.0

    key = f"{base}{quote}"
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        hist = yf.Ticker(f"{key}=X").history(period="5d")
        rate = float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        rate = None

    if rate is None:
        return cached[1] if cached else None

    _cache[key] = (time.time(), rate)
    return rate
