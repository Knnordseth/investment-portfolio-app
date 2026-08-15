"""Plugin registry for signals. To add a new signal: create a module in this package with an
`evaluate(df) -> SignalResult` function decorated with @register("name"), then import it at the
bottom of this file. Nothing else needs to change — app.py picks it up automatically.
"""

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass
class SignalResult:
    signal: str
    action: str  # "buy" | "sell" | "hold"
    confidence: float  # 0.0-1.0, how strongly the signal is firing
    reason: str  # human-readable explanation — never show a signal without one


REGISTRY: dict[str, Callable[[pd.DataFrame], SignalResult]] = {}


def register(name: str):
    def wrapper(fn):
        REGISTRY[name] = fn
        return fn

    return wrapper


def confluence(results: list[SignalResult]) -> SignalResult:
    """Combine every registered signal into one verdict instead of trusting any single
    indicator alone — RSI, MACD and the MA crossover are all lagging and frequently
    disagree, which is exactly why single-indicator "buy" badges are noisy. Two rules:
    require at least 2 non-hold signals to agree (and outnumber the ones disagreeing)
    before calling it real; and let the 200-day trend act as a gate rather than an equal
    vote — an RSI "oversold" buy against a confirmed long-term downtrend is a falling
    knife, not a dip, so it gets its confidence cut, not an outright veto (the other
    indicators might still be right)."""
    votes = [r for r in results if r.action != "hold" and r.confidence > 0]
    if not votes:
        return SignalResult("confluence", "hold", 0.0, "no indicators are firing")

    buy_votes = [r for r in votes if r.action == "buy"]
    sell_votes = [r for r in votes if r.action == "sell"]
    buy_score = sum(r.confidence for r in buy_votes)
    sell_score = sum(r.confidence for r in sell_votes)

    trend = next((r for r in results if r.signal == "sma_trend"), None)
    if trend and trend.confidence > 0:
        if trend.action == "sell" and buy_score > sell_score:
            buy_score *= 0.4
        elif trend.action == "buy" and sell_score > buy_score:
            sell_score *= 0.4

    if buy_score >= sell_score:
        direction, score, agreeing, opposing = "buy", buy_score, buy_votes, sell_votes
    else:
        direction, score, agreeing, opposing = "sell", sell_score, sell_votes, buy_votes

    if len(agreeing) < 2:
        # Distinct from the "genuine disagreement" case below — with fewer than 2 votes
        # on the stronger side there's nothing to actually disagree with, so saying so
        # read as nonsense (e.g. a single "sma_trend=sell" being called a "disagreement").
        names = ", ".join(f"{r.signal}={r.action}" for r in votes)
        return SignalResult("confluence", "hold", 0.0, f"not enough signals agree yet ({names})")

    if len(agreeing) <= len(opposing):
        names = ", ".join(f"{r.signal}={r.action}" for r in votes)
        return SignalResult("confluence", "hold", 0.0, f"signals are split, no clear majority ({names})")

    confidence = round(min(score / len(agreeing), 1.0), 2)
    names = ", ".join(r.signal for r in agreeing)
    gate_note = " — against the 200-day trend, weighted down accordingly" if trend and trend.action != direction and trend.confidence > 0 else ""
    return SignalResult("confluence", direction, confidence, f"{len(agreeing)} signals agree ({names}){gate_note}")


def evaluate_all(df: pd.DataFrame) -> list[SignalResult]:
    results = [fn(df) for fn in REGISTRY.values()]
    results.append(confluence(results))
    return results


# Import signal modules so their @register decorators run.
from . import rsi, ma_crossover, macd, sma_trend  # noqa: E402,F401
