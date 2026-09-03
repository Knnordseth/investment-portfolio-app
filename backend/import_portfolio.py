"""Import portfolio data from Nordnet CSV export.

Run with: python import_portfolio.py path/to/export.csv
Export it from Nordnet: Portfolio -> Transactions -> Export (choose the tab-separated,
UTF-16 "per position" format).
"""

import csv
import sys
from datetime import datetime
import db

# Asset categorization - funds vs individual stocks
FUNDS = {
    'DNB', 'DNB Norden Indeks A',
    'KLPE', 'KLP AksjeEuropa Indeks N',
    'KLPU', 'KLP AksjeUSA Indeks N',
    'NDEM', 'Nordnet Emerging Markets Indeks',
    'NOFF', 'Nordnet One Offensiv NOK',
}

def get_category(symbol: str) -> str:
    """Determine if asset is a fund or individual stock."""
    return 'fund' if symbol in FUNDS else 'stock'

def parse_csv(csv_path):
    """Parse Nordnet CSV and aggregate by symbol, preserving market values."""
    holdings_dict = {}
    
    # Read the Unicode/UTF-16 encoded CSV
    with open(csv_path, 'r', encoding='utf-16') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            if not row.get('Symbol'):
                continue
            
            symbol = row['Symbol'].strip()
            try:
                quantity = float(row['Quantity'].replace(',', '.').strip())
                purchase_price = float(row['Purchase price (NOK)'].replace(',', '.').strip())
                market_value = float(row['Market value (NOK)'].replace(',', '.').strip())
                
                if symbol not in holdings_dict:
                    holdings_dict[symbol] = {
                        'quantity': 0,
                        'cost': 0,
                        'market_value': 0
                    }
                
                holdings_dict[symbol]['quantity'] += quantity
                holdings_dict[symbol]['cost'] += quantity * purchase_price
                holdings_dict[symbol]['market_value'] += market_value
            except (ValueError, KeyError) as e:
                print(f"Skipped row: {symbol} - Error: {e}")
                continue
    
    # Calculate average price per symbol, skipping positions Nordnet shows as fully
    # sold/closed (net quantity <= 0 after summing all lots for that symbol).
    portfolio = []
    for symbol, data in holdings_dict.items():
        if data['quantity'] <= 0:
            print(f"Skipped {symbol} — sold position (net quantity {data['quantity']:.4f})")
            continue

        avg_price = data['cost'] / data['quantity']
        category = get_category(symbol)
        portfolio.append((
            symbol,
            'stock',
            category,
            data['quantity'],
            avg_price,
            data['market_value']
        ))

    return sorted(portfolio, key=lambda x: x[0])


def import_portfolio(csv_path):
    """Load all holdings from CSV into the database."""
    db.init_db()
    
    # Clear ONLY Nordnet holdings (stocks/funds), keep crypto
    with db.get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE category IN ('stock', 'fund')")
    
    portfolio = parse_csv(csv_path)
    
    total_market_value = 0
    for symbol, asset_type, category, quantity, avg_price, market_value in portfolio:
        holding_id = db.add_holding(
            symbol, 
            asset_type, 
            quantity, 
            abs(avg_price), 
            category,
            market_value,
            datetime.now().isoformat()
        )
        cat_label = category.upper()
        total_market_value += market_value
        print(f"Added {symbol:<35} ({cat_label}): {quantity:>8.4f} @ {abs(avg_price):>10.2f} NOK | Market: {market_value:>12,.0f} NOK -> ID {holding_id}")
    
    # Separate counts
    funds = [p for p in portfolio if p[2] == 'fund']
    stocks = [p for p in portfolio if p[2] == 'stock']
    
    print(f"\nImported: {len(portfolio)} assets | Funds: {len(funds)} | Stocks: {len(stocks)}")
    print(f"Total Market Value (Nordnet): {total_market_value:,.0f} NOK")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python import_portfolio.py path/to/nordnet-export.csv")
    import_portfolio(sys.argv[1])
