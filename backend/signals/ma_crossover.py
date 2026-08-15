from . import SignalResult, register


@register("ma_crossover")
def evaluate(df) -> SignalResult:
    if len(df) < 51:
        return SignalResult("ma_crossover", "hold", 0.0, "not enough price history for 50-day MA")

    closes = df["Close"]
    sma20 = closes.rolling(20).mean()
    sma50 = closes.rolling(50).mean()
    prev_diff = sma20.iloc[-2] - sma50.iloc[-2]
    curr_diff = sma20.iloc[-1] - sma50.iloc[-1]

    if prev_diff <= 0 < curr_diff:
        return SignalResult("ma_crossover", "buy", 0.7, "20-day MA crossed above 50-day MA (golden cross)")
    if prev_diff >= 0 > curr_diff:
        return SignalResult("ma_crossover", "sell", 0.7, "20-day MA crossed below 50-day MA (death cross)")

    trend = "above" if curr_diff > 0 else "below"
    return SignalResult("ma_crossover", "hold", 0.0, f"20-day MA is {trend} 50-day MA, no fresh crossover")
