"""SQLite storage for holdings and watchlist. One file, no server — good enough for a local, single-user app."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "portfolio.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'crypto', 'real_estate')),
    category TEXT CHECK (category IN ('stock', 'fund', 'crypto', 'real_estate')) DEFAULT 'stock',
    quantity REAL NOT NULL,
    avg_price REAL NOT NULL,
    nordnet_market_value REAL DEFAULT 0,
    nordnet_last_updated TEXT,
    annual_growth_pct REAL,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    asset_type TEXT NOT NULL CHECK (asset_type IN ('stock', 'crypto')),
    note TEXT DEFAULT '',
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    price REAL NOT NULL,
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    date TEXT PRIMARY KEY,
    total_value_nok REAL NOT NULL,
    by_category_json TEXT NOT NULL
);
"""


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection):
    """SQLite can't ALTER a CHECK constraint or column set in place, so a schema change
    that widens either (like adding the 'real_estate' asset_type/category, or the
    annual_growth_pct column) needs the rebuild-and-copy dance instead."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(holdings)")}
    if "annual_growth_pct" in columns:
        return

    conn.execute("ALTER TABLE holdings RENAME TO holdings_old")
    conn.executescript(SCHEMA)
    conn.execute("""
        INSERT INTO holdings (id, symbol, asset_type, category, quantity, avg_price,
                               nordnet_market_value, nordnet_last_updated, added_at)
        SELECT id, symbol, asset_type, category, quantity, avg_price,
               nordnet_market_value, nordnet_last_updated, added_at
        FROM holdings_old
    """)
    conn.execute("DROP TABLE holdings_old")


def init_db():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _now():
    return datetime.now(timezone.utc).isoformat()


def add_holding(symbol: str, asset_type: str, quantity: float, avg_price: float, category: str = "stock", nordnet_market_value: float = 0, nordnet_last_updated: str = None, annual_growth_pct: float = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO holdings (symbol, asset_type, category, quantity, avg_price, nordnet_market_value, nordnet_last_updated, annual_growth_pct, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol.upper(), asset_type, category, quantity, avg_price, nordnet_market_value, nordnet_last_updated, annual_growth_pct, _now()),
        )
        return cur.lastrowid


def list_holdings() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM holdings ORDER BY symbol").fetchall()
        return [dict(row) for row in rows]


def remove_holding(holding_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


def add_watchlist(symbol: str, asset_type: str, note: str = "") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO watchlist (symbol, asset_type, note, added_at) VALUES (?, ?, ?, ?)",
            (symbol.upper(), asset_type, note, _now()),
        )
        return cur.lastrowid


def list_watchlist() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM watchlist ORDER BY symbol").fetchall()
        return [dict(row) for row in rows]


def remove_watchlist(watchlist_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE id = ?", (watchlist_id,))


def save_price_history(symbol: str, date: str, price: float):
    """Save daily price point for a symbol."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_history (symbol, date, price) VALUES (?, ?, ?)",
            (symbol.upper(), date, price),
        )


def get_price_history(symbol: str, days: int = 365) -> list[dict]:
    """Get price history for a symbol (default last year)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, price FROM price_history WHERE symbol = ? ORDER BY date DESC LIMIT ?",
            (symbol.upper(), days),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]  # chronological order


def save_snapshot(date: str, total_value_nok: float, by_category_json: str):
    """One row per calendar day — overwritten on every /api/allocation call that day, so
    the stored value is always the latest one computed, not just the first."""
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_snapshots (date, total_value_nok, by_category_json) VALUES (?, ?, ?)",
            (date, total_value_nok, by_category_json),
        )


def get_snapshots(days: int = 365) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date, total_value_nok, by_category_json FROM portfolio_snapshots ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]  # chronological order
