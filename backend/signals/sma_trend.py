from . import SignalResult, register


@register("sma_trend")
def evaluate(df) -> SignalResult:
    """Long-term trend gate via the 200-day SMA. Not a trigger on its own — its real job is
    context for the other signals: an RSI "buy" (oversold) firing while price is well below
    its 200-day average is a falling knife, not a dip. See confluence() in __init__.py."""
    if len(df) < 200:
        return SignalResult("sma_trend", "hold", 0.0, "not enough price history for 200-day trend")

    closes = df["Close"]
    sma200 = closes.rolling(200).mean().iloc[-1]
    price = closes.iloc[-1]
    if not sma200:
        return SignalResult("sma_trend", "hold", 0.0, "200-day trend unavailable")

    diff_pct = (price - sma200) / sma200 * 100
    confidence = round(min(abs(diff_pct) / 20, 1.0), 2)

    if price >= sma200:
        return SignalResult("sma_trend", "buy", confidence, f"price is {diff_pct:.1f}% above its 200-day average — long-term uptrend")
    return SignalResult("sma_trend", "sell", confidence, f"price is {abs(diff_pct):.1f}% below its 200-day average — long-term downtrend")
