# Investment Portfolio App

Local dashboard for stock + crypto holdings and watchlist, with rules-based buy/sell signals.
Utility-first: every signal comes with a plain-English reason, not just an arrow.

## Stack

- **Backend**: Python + FastAPI. `backend/app.py` serves the API under `/api/*` and the
  static frontend at `/`.
- **Storage**: SQLite (`backend/portfolio.db`, created on first run). One file, no setup.
- **Stock data**: [yfinance](https://github.com/ranaroussi/yfinance) — free, delayed, no API key.
- **Crypto data**: direct REST calls to [Firi](https://firi.com) (`backend/data_sources/crypto_firi.py`).
  Firi isn't in `ccxt`, so this talks to `api.firi.com/v2` directly. Public ticker/history
  endpoints work with no key; balances/orders need `FIRI_API_KEY` (see `.env.example`).
- **Frontend**: plain HTML/CSS/JS, no build step. Dark terminal theme (black + green,
  monospace) in `frontend/`.

## Signals — plugin architecture

`backend/signals/` is a small registry. Each signal is a module with an `evaluate(df) ->
SignalResult` function decorated with `@register("name")`. To add a new signal: drop a new
file in that folder, import it at the bottom of `signals/__init__.py`, done — nothing else
changes.

Shipped so far:
- **RSI** — oversold (<30) = buy, overbought (>70) = sell.
- **MA crossover** — 20-day/50-day SMA golden cross = buy, death cross = sell.

Both are rules-based on purpose: explainable now, easy to layer smarter logic on top later.

## Running it locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000 — dashboard, add holdings/watchlist entries, signals refresh
every 60s.

For crypto private endpoints, copy `backend/.env.example` to `backend/.env` and fill in
`FIRI_API_KEY` (Firi account → Settings → API).

## Roadmap / not-yet-decided

- Price charts (TradingView Lightweight Charts is the natural fit for the theme — not wired
  up yet, current focus is the signal table).
- News feed per position.
- Remote access: local-first for now; when ready to check from a phone, put a private tunnel
  (e.g. Tailscale) in front of `uvicorn` rather than exposing it directly.
- More signals (MACD, volume spikes, volatility-based position sizing hints).

## Note

A separate `Portfolio app.md` note in this folder is unrelated — it's a personal portfolio
*website* (batcave.no), not investment tracking. Not merged into this app.
