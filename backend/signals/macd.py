from . import SignalResult, register


@register("macd")
def evaluate(df) -> SignalResult:
    """MACD (12/26/9 EMA): momentum + trend confirmation, distinct from RSI's pure
    overbought/oversold read — RSI can stay "oversold" through an entire downtrend,
    MACD instead reacts to the trend's own momentum shifting."""
    if len(df) < 35:
        return SignalResult("macd", "hold", 0.0, "not enough price history for MACD")

    closes = df["Close"]
    macd_line = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line

    prev_hist, curr_hist = hist.iloc[-2], hist.iloc[-1]
    price = closes.iloc[-1]
    confidence = round(min(abs(curr_hist) / price * 40, 1.0), 2) if price else 0.0

    if prev_hist <= 0 < curr_hist:
        return SignalResult("macd", "buy", confidence, "MACD crossed above its signal line (bullish momentum shift)")
    if prev_hist >= 0 > curr_hist:
        return SignalResult("macd", "sell", confidence, "MACD crossed below its signal line (bearish momentum shift)")

    trend = "above" if curr_hist > 0 else "below"
    return SignalResult("macd", "hold", 0.0, f"MACD is {trend} its signal line, no fresh crossover")
