"""Free, delayed stock data via yfinance. No API key needed."""

import time
from functools import lru_cache

import pandas as pd
import yfinance as yf

# Nordnet exports symbols without an exchange suffix (e.g. "GJF", "KOG"), but Yahoo
# Finance needs one for anything outside the US ("GJF.OL"). Some symbols also use a
# space where Yahoo expects a dash (e.g. "NOVO B" -> "NOVO-B.CO"). Try the raw symbol
# first (covers US tickers), then probe these fallbacks.
_FALLBACK_SUFFIXES = [".OL", ".ST", ".CO", ".HE"]

# import_portfolio.py books avg_price in NOK (Nordnet's account currency) no matter
# what exchange the holding actually trades on — but a resolved Yahoo symbol like a
# bare US ticker returns prices in ITS OWN currency (USD, DKK, ...). Without converting,
# latest_price ends up in a different currency than avg_price for every foreign-listed
# holding, which silently produced nonsense gain/loss (e.g. MSTR looked like -94% when
# the real move was much smaller) and made sorting by Value/Gain-Loss meaningless.
_FX_CACHE_TTL_SECONDS = 3600
_currency_cache: dict[str, str] = {}
_fx_cache: dict[str, tuple[float, float]] = {}


def _currency_of(resolved_symbol: str) -> str:
    if resolved_symbol in _currency_cache:
        return _currency_cache[resolved_symbol]
    try:
        currency = (yf.Ticker(resolved_symbol).info.get("currency") or "NOK").upper()
    except Exception:
        currency = "NOK"
    _currency_cache[resolved_symbol] = currency
    return currency


def _fx_rate_to_nok(currency: str) -> float:
    """Constant-scaling the whole history by today's rate (rather than each day's
    historical rate) is fine here: RSI/MACD/MA-crossover only care about relative
    moves, which a uniform scale factor doesn't change, and the Performance panel's
    % change is a ratio against day 0 of the same series, so the factor cancels out
    entirely. Only today's absolute NOK value (Value/Gain-Loss) needs to be exact,
    and that's exactly what today's live rate gives it."""
    if currency == "NOK":
        return 1.0
    cached = _fx_cache.get(currency)
    if cached and time.time() - cached[0] < _FX_CACHE_TTL_SECONDS:
        return cached[1]
    try:
        hist = yf.Ticker(f"{currency}NOK=X").history(period="5d")
        rate = float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        rate = None
    if rate is None:
        rate = cached[1] if cached else 1.0
    _fx_cache[currency] = (time.time(), rate)
    return rate


def _fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
    return yf.Ticker(symbol).history(period=period, interval=interval)


@lru_cache(maxsize=256)
def resolve_symbol(symbol: str) -> str | None:
    """Find a Yahoo Finance symbol that actually returns data for this Nordnet-style
    symbol. Cached per process so repeated dashboard polls don't re-probe yfinance.

    Suffixed candidates are tried BEFORE the bare symbol. This portfolio is sourced
    from a Nordic broker (Nordnet), and short codes like "KMAR" collide with unrelated
    tickers on other exchanges (KMAR alone matches a US ETF; the actual holding is
    Kongsberg Maritime, KMAR.OL) — trying suffixes first avoids silently returning the
    wrong instrument's price/signals for a real US ticker that happens to share a code.
    """
    bases = [symbol]
    dashed = symbol.replace(" ", "-")
    if dashed != symbol:
        bases.append(dashed)

    candidates = [f"{base}{suffix}" for base in bases for suffix in _FALLBACK_SUFFIXES]
    candidates.extend(bases)

    for candidate in candidates:
        try:
            hist = _fetch(candidate, period="5d", interval="1d")
        except Exception:
            continue
        if not hist.empty:
            return candidate
    return None


def get_price_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Returns a DataFrame indexed by date with Open/High/Low/Close/Volume columns, in NOK."""
    resolved = resolve_symbol(symbol)
    if resolved is None:
        return pd.DataFrame()

    hist = _fetch(resolved, period=period, interval=interval)
    if hist.empty:
        return hist

    # Yahoo appends a placeholder row for the current session before that day's data is
    # final (seen live on Oslo Børs names: today's Close came back NaN while the market
    # was still open) — drop it, same as funds.py already does, so a NaN never reaches
    # latest_price/signals and crashes the response (JSON doesn't allow NaN).
    hist = hist.dropna(subset=["Close"])
    if hist.empty:
        return hist

    rate = _fx_rate_to_nok(_currency_of(resolved))
    if rate != 1.0:
        for col in ("Open", "High", "Low", "Close"):
            if col in hist.columns:
                hist[col] = hist[col] * rate

    return hist


def get_latest_price(symbol: str) -> float | None:
    hist = get_price_history(symbol, period="5d")
    if hist.empty:
        return None
    return float(hist["Close"].iloc[-1])
