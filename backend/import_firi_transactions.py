"""Import Firi transaction CSV and build current crypto balances.

This is intentionally short: the exported CSV is a transaction ledger, not an order book.
We only need Action + Currency + Amount to calculate net position per asset.

Run with: python import_firi_transactions.py path/to/transactions.csv
Export it from Firi: Account -> Transaction history -> Export CSV.
"""

import csv
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

import db
from import_firi import get_firi_ticker
from data_sources import crypto_coingecko


def parse_decimal(value):
    if value is None:
        return Decimal("0")
    value = str(value).strip().replace("'", "")
    if not value:
        return Decimal("0")
    try:
        return Decimal(value)
    except InvalidOperation:
        return Decimal("0")


def read_transaction_totals(csv_path):
    """Aggregate net quantities per crypto from Firi transaction CSV."""
    totals = defaultdict(Decimal)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            action = (row.get("Action") or "").strip()
            currency = (row.get("Currency") or "").strip().upper()
            if not action or not currency or currency == "NOK":
                continue

            amount = parse_decimal(row.get("Amount"))
            if amount == 0:
                continue

            totals[currency] += amount

    return {symbol: float(total) for symbol, total in sorted(totals.items())}


def import_from_csv(csv_path):
    """Insert the net crypto position into the DB."""
    db.init_db()

    with db.get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE category = 'crypto'")

    totals = read_transaction_totals(csv_path)
    imported = 0
    total_value = 0

    for symbol, quantity in totals.items():
        if quantity <= 0:
            continue

        market = f"{symbol}NOK"
        ticker = get_firi_ticker(market)
        if ticker and ("bid" in ticker or "ask" in ticker):
            bid = float(ticker.get("bid", 0) or 0)
            ask = float(ticker.get("ask", 0) or 0)
            price = (bid + ask) / 2 if bid and ask else max(bid, ask)
        else:
            price = 0.0

        # No Firi market for this coin (e.g. AVAX, DOGE, LINK, XLM) — fall back to CoinGecko.
        if price <= 0:
            fallback_price = crypto_coingecko.get_current_price(symbol)
            if fallback_price:
                price = fallback_price

        value = quantity * price if price else 0.0
        total_value += value

        db.add_holding(
            symbol=symbol,
            asset_type="crypto",
            quantity=quantity,
            avg_price=price,
            category="crypto",
            nordnet_market_value=value,
            nordnet_last_updated=None,
        )
        imported += 1
        print(f"Added {symbol:<6} qty={quantity:>12.8f} @ {price:>10.2f} NOK value={value:>12.2f} NOK")

    print(f"\nImported {imported} crypto positions from CSV")
    print(f"Total value: {total_value:,.0f} NOK")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python import_firi_transactions.py path/to/transactions.csv")
    import_from_csv(Path(sys.argv[1]))
