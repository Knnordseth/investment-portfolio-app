"""Import crypto holdings from Firi's /v2/balances API.

DO NOT use import_firi_balances() as the primary way to (re-)populate crypto holdings if
any coins are in Firi's Staking feature: /v2/balances only reports the liquid trading
wallet — staked coins are moved out of it entirely, and Firi's API has no endpoint that
reports staked balances (confirmed against their published OpenAPI spec: no /staking or
/spare path exists at all). Verified live: this undercounted BTC by 71% and showed AVAX/
LINK/SOL as zero when substantial amounts of each were staked.

Use import_firi_transactions.py instead — it reconstructs the true position (including
whatever's currently staked, plus staking rewards) from the full transaction ledger CSV,
which is the only place that information is exposed at all. get_firi_ticker() from this
module is still used by that script for live pricing; only import_firi_balances() itself
is the part to avoid."""

import ca_bundle  # noqa: F401 — must run before anything makes an HTTPS call

import os
from datetime import datetime
import requests
import db
from data_sources import crypto_coingecko

# Load from .env
from dotenv import load_dotenv
load_dotenv()

BASE_URL = "https://api.firi.com/v2"


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_firi_balances():
    """Fetch crypto balances from Firi's /balances endpoint — the only balance endpoint
    Firi's API actually exposes (verified live: /wallets, /accounts, /portfolio, /savings,
    and /staking all 404). An earlier version of this function also queried those extra
    endpoints and summed every result together under the theory that Firi split holdings
    across separate wallet/savings/staking "buckets" — if Firi's API ever did (or again
    does) expose a real separate savings balance for the same currency, that would have
    silently double-counted it on top of /balances, which already reports the account
    total. Don't reintroduce that without confirming each endpoint returns a genuinely
    additional, non-overlapping balance."""
    api_key = os.getenv("FIRI_API_KEY")
    if not api_key:
        print("❌ FIRI_API_KEY not set in .env")
        return None

    headers = {"firi-access-key": api_key}
    try:
        resp = requests.get(f"{BASE_URL}/balances", headers=headers, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Firi API error: {e}")
        return None

    if not isinstance(payload, list):
        print(f"❌ Unexpected /balances response shape: {type(payload).__name__}")
        return None

    rows = [
        {"currency": item["currency"].upper(), "available": _as_float(item.get("available", item.get("balance", 0)))}
        for item in payload
        if item.get("currency")
    ]
    rows = [r for r in rows if r["available"] > 0]
    if rows:
        print(f"Fetched {len(rows)} crypto balance rows from Firi /balances")
    return rows


def get_firi_ticker(market: str) -> dict:
    """Get current price for a market pair (e.g., 'BTCNOK').
    Falls back to trying USDT pair if NOK pair doesn't exist."""
    api_key = os.getenv("FIRI_API_KEY")
    headers = {"firi-access-key": api_key} if api_key else {}
    
    # Try NOK first
    try:
        resp = requests.get(f"{BASE_URL}/markets/{market}/ticker", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException:
        pass
    
    # Try USDT as fallback (if original was XXXNOK, try XXXUSDT)
    if market.endswith("NOK"):
        alt_market = market.replace("NOK", "USDT")
        try:
            resp = requests.get(f"{BASE_URL}/markets/{alt_market}/ticker", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # Mark that this is USDT price, not NOK
            data["_note"] = "USDT price (conversion needed)"
            return data
        except requests.exceptions.RequestException:
            pass
    
    return {}


def import_firi_balances():
    """Fetch Firi balances and add to holdings as crypto (preserves existing Nordnet holdings)."""
    db.init_db()
    
    # Clear ONLY existing crypto holdings, keep stocks/funds
    with db.get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE category = 'crypto'")
    
    balances = get_firi_balances()
    if not balances:
        print("No balances fetched. Check API key and network.")
        return
    
    print(f"Fetched {len(balances)} unique balances from Firi")
    
    # Filter to holdings > 0 and convert to holdings
    imported_count = 0
    total_market_value = 0
    for balance in balances:
        symbol = balance.get("currency", "").upper()
        available = float(balance.get("available", 0))
        
        if available <= 0 or not symbol:
            continue
        
        # Get current price to calculate market value
        market = f"{symbol}NOK"
        ticker = get_firi_ticker(market)

        # Firi returns bid/ask, use midpoint or ask price
        if ticker and ("bid" in ticker or "ask" in ticker):
            bid = float(ticker.get("bid", 0))
            ask = float(ticker.get("ask", 0))
            current_price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)
        else:
            current_price = 0

        # Firi doesn't list a market at all for some coins (AVAX, DOGE, LINK, XLM as of
        # this writing) — its ticker endpoint just returns an error for those, leaving
        # current_price at 0. Fall back to CoinGecko's public price for those.
        if current_price <= 0:
            fallback_price = crypto_coingecko.get_current_price(symbol)
            if fallback_price:
                current_price = fallback_price
                print(f"  (using CoinGecko price for {symbol} - no Firi market for this pair)")

        market_value = available * current_price if current_price > 0 else 0
        total_market_value += market_value
        
        # Use current price as avg_price (we don't have cost basis from Firi easily)
        holding_id = db.add_holding(
            symbol=symbol,
            asset_type="crypto",
            quantity=available,
            avg_price=current_price,
            category="crypto",
            nordnet_market_value=market_value,
            nordnet_last_updated=datetime.now().isoformat()
        )
        
        print(f"Added {symbol:<6} (CRYPTO): {available:>12.8f} @ {current_price:>10.2f} NOK | Market: {market_value:>12,.0f} NOK -> ID {holding_id}")
        imported_count += 1
    
    print(f"\nImported {imported_count} crypto holdings from Firi")
    print(f"Total Market Value (Firi): {total_market_value:,.0f} NOK")


if __name__ == "__main__":
    import_firi_balances()
