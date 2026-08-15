import pandas as pd

from . import SignalResult, register


def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


@register("rsi")
def evaluate(df: pd.DataFrame) -> SignalResult:
    if len(df) < 15:
        return SignalResult("rsi", "hold", 0.0, "not enough price history")

    latest = _rsi(df["Close"]).iloc[-1]
    if pd.isna(latest):
        return SignalResult("rsi", "hold", 0.0, "RSI unavailable")
    if latest < 30:
        return SignalResult("rsi", "buy", round((30 - latest) / 30, 2), f"RSI at {latest:.1f} — oversold")
    if latest > 70:
        return SignalResult("rsi", "sell", round((latest - 70) / 30, 2), f"RSI at {latest:.1f} — overbought")
    return SignalResult("rsi", "hold", 0.0, f"RSI at {latest:.1f} — neutral")
