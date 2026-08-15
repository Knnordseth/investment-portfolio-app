"""Picks one candidate (from current holdings + watchlist) with the best estimated
growth potential for a next monthly buy.

Deliberately transparent, not a black box: every score is a sum of named, visible
components (see `reasons`), not a single opaque number. This is a heuristic built from
whatever data this app already has — analyst targets, distance from all-time-high for
crypto, recent momentum, and the confluence signal — not investment advice.
"""

from data_sources import crypto_firi, fundamentals, funds, stocks
from signals import evaluate_all


def _price_history(symbol: str, category: str):
    if category == "fund":
        return funds.get_price_history(symbol)
    if category == "crypto":
        return crypto_firi.get_daily_close_history(symbol)
    return stocks.get_price_history(symbol)


def score_candidate(symbol: str, category: str) -> dict | None:
    try:
        df = _price_history(symbol, category)
    except Exception:
        return None
    if df is None or df.empty:
        return None

    closes = df["Close"].dropna()
    if closes.empty:
        return None
    current_price = float(closes.iloc[-1])

    confluence = next((r for r in evaluate_all(df) if r.signal == "confluence"), None)
    fund_data = fundamentals.get_fundamentals(symbol, category)

    score = 0.0
    reasons = []

    analyst_upside_pct = None
    if fund_data.get("available") and fund_data.get("analyst_target_mean") and current_price:
        analyst_upside_pct = round((fund_data["analyst_target_mean"] / current_price - 1) * 100, 2)
        score += analyst_upside_pct
        reasons.append(f"analyst target implies {analyst_upside_pct:+.1f}% upside")

    ath_recovery_pct = None
    if category == "crypto" and fund_data.get("available") and fund_data.get("ath") and current_price:
        ath_recovery_pct = round((fund_data["ath"] / current_price - 1) * 100, 2)
        score += ath_recovery_pct * 0.3  # speculative vs. an analyst target — discounted accordingly
        reasons.append(f"{ath_recovery_pct:+.1f}% below its all-time high")

    if confluence and confluence.action != "hold" and confluence.confidence > 0:
        bonus = confluence.confidence * 15
        score += bonus if confluence.action == "buy" else -bonus
        reasons.append(f"confluence signal is {confluence.action} — {confluence.reason}")

    # Last-resort signal only when nothing fundamentals-based is available (e.g. a crypto
    # with no CoinGecko match), so every candidate has at least one reason behind its score.
    if analyst_upside_pct is None and ath_recovery_pct is None:
        window = closes.tail(30)
        if len(window) > 1:
            momentum_pct = round((float(window.iloc[-1]) / float(window.iloc[0]) - 1) * 100, 2)
            score += momentum_pct * 0.2
            reasons.append(f"{momentum_pct:+.1f}% over the last 30 days")

    if not reasons:
        reasons.append("no fundamentals, ATH, or momentum data available — score is signal-only")

    return {
        "symbol": symbol,
        "category": category,
        "current_price": round(current_price, 2),
        "score": round(score, 2),
        "analyst_upside_pct": analyst_upside_pct,
        "confluence_action": confluence.action if confluence else None,
        "confluence_confidence": confluence.confidence if confluence else None,
        "reasons": reasons,
    }


def recommend(candidates: list[dict]) -> dict:
    scored = []
    for c in candidates:
        result = score_candidate(c["symbol"], c.get("category") or c.get("asset_type") or "stock")
        if result:
            scored.append(result)

    scored.sort(key=lambda r: r["score"], reverse=True)
    return {
        "pick": scored[0] if scored else None,
        "ranked": scored,
        "disclaimer": "Heuristic score from analyst targets, distance from all-time high (crypto), recent momentum, "
                       "and the confluence signal — not investment advice.",
    }
