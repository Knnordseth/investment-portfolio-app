"""Backtest the confluence signal against simple buy-and-hold, so its output can be
trusted (or not) with real money instead of taken on faith.

Walks the price history day by day using ONLY the data that would have been available
at that point (df.iloc[:i+1]) through the same evaluate_all() the live dashboard calls —
so this reproduces exactly what the app would have told you to do at each point in time,
with no lookahead bias. All-in/all-out position sizing (100% in or 100% cash), no fees,
no slippage — a real broker would erode the strategy's edge further, not less.
"""

from dataclasses import asdict, dataclass

import pandas as pd

from signals import evaluate_all


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    return_pct: float


def backtest(df: pd.DataFrame, min_history: int = 20) -> dict:
    closes = df["Close"].dropna()
    if len(closes) < min_history + 5:
        return {"available": False, "note": "not enough price history to backtest"}

    trades: list[Trade] = []
    in_position = False
    entry_price = None
    entry_date = None

    for i in range(min_history, len(closes)):
        window = df.iloc[: i + 1]
        results = evaluate_all(window)
        confluence = next((r for r in results if r.signal == "confluence"), None)
        if confluence is None:
            continue

        price = float(closes.iloc[i])
        idx_date = str(closes.index[i].date())

        if not in_position and confluence.action == "buy":
            in_position, entry_price, entry_date = True, price, idx_date
        elif in_position and confluence.action == "sell":
            trades.append(Trade(entry_date, entry_price, idx_date, price, round((price / entry_price - 1) * 100, 2)))
            in_position, entry_price, entry_date = False, None, None

    open_position = None
    if in_position:
        last_price = float(closes.iloc[-1])
        open_position = {
            "entry_date": entry_date,
            "entry_price": round(entry_price, 2),
            "current_price": round(last_price, 2),
            "unrealized_return_pct": round((last_price / entry_price - 1) * 100, 2),
        }

    strategy_multiplier = 1.0
    for t in trades:
        strategy_multiplier *= t.exit_price / t.entry_price
    if open_position:
        strategy_multiplier *= open_position["current_price"] / open_position["entry_price"]

    buy_hold_return_pct = round((float(closes.iloc[-1]) / float(closes.iloc[min_history]) - 1) * 100, 2)
    wins = sum(1 for t in trades if t.return_pct > 0)

    return {
        "available": True,
        "start_date": str(closes.index[min_history].date()),
        "end_date": str(closes.index[-1].date()),
        "buy_hold_return_pct": buy_hold_return_pct,
        "strategy_return_pct": round((strategy_multiplier - 1) * 100, 2),
        "trade_count": len(trades),
        "win_rate_pct": round(wins / len(trades) * 100, 1) if trades else None,
        "trades": [asdict(t) for t in trades],
        "open_position": open_position,
    }
