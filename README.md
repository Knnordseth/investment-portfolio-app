# Investment Portfolio App

Local dashboard for stock, fund, crypto, and real estate holdings plus a watchlist, with
rules-based buy/sell signals and a "Priority Pick" that scores everything you hold or watch
for what to prioritize buying next. Utility-first: every signal comes with a plain-English
reason, not just an arrow.

Runs entirely on your own machine. Nothing you enter — holdings, watchlist, API keys — ever
leaves it or gets committed to git (see [Your data stays local](#your-data-stays-local)).

## Quick start

```bash
git clone https://github.com/Knnordseth/investment-portfolio-app.git
cd investment-portfolio-app/backend
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000. There's no seed data — the database is created empty on first
run — so the dashboard starts blank. Add holdings and watchlist entries straight from the
forms at the bottom of each table; everything (signals, allocation, Priority Pick) refreshes
from there.

If you have a Nordnet or Firi export handy, `backend/import_portfolio.py` and
`backend/import_firi_transactions.py` can bulk-load one instead of typing rows in by hand —
see [Bulk-importing from a broker export](#bulk-importing-from-a-broker-export).

## Stack

- **Backend**: Python + FastAPI. `backend/app.py` serves the API under `/api/*` and the
  static frontend at `/`.
- **Storage**: SQLite (`backend/portfolio.db`, created on first run, gitignored). One file,
  no setup.
- **Stock data**: [yfinance](https://github.com/ranaroussi/yfinance) — free, delayed, no API key.
- **Crypto data**: direct REST calls to [Firi](https://firi.com) (`backend/data_sources/crypto_firi.py`).
  Firi isn't in `ccxt`, so this talks to `api.firi.com/v2` directly. Public ticker/history
  endpoints work with no key; balances/orders need `FIRI_API_KEY` (see `.env.example`).
- **Real estate**: manually entered (value + an optional estimated annual appreciation %) —
  there's no market feed for it, so it's tracked separately from the stock/fund/crypto
  allocation and only rolled into net worth.
- **Frontend**: plain HTML/CSS/JS, no build step. Dark terminal theme (black + green,
  monospace) in `frontend/`.

## Signals — plugin architecture

`backend/signals/` is a small registry. Each signal is a module with an `evaluate(df) ->
SignalResult` function decorated with `@register("name")`. To add a new signal: drop a new
file in that folder, import it at the bottom of `signals/__init__.py`, done — nothing else
changes.

Shipped so far: RSI, MA crossover, MACD, and an SMA trend filter — all rules-based on
purpose: explainable now, easy to layer smarter logic on top later.

## Priority Pick

Scores every current holding + watchlist entry (analyst-target upside, momentum, and the
confluence signal) and surfaces the single best candidate to prioritize buying next, with
the full ranked list and the reasons behind each score for transparency. It's a heuristic
built from data this app already has — not investment advice.

## Bulk-importing from a broker export

Both importers take the exported file as a command-line argument and only touch their own
asset category (re-running one clears and replaces just that category — e.g. re-importing
Nordnet won't touch your crypto rows):

```bash
python import_portfolio.py path/to/nordnet-export.csv          # stocks + funds
python import_firi_transactions.py path/to/transactions.csv    # crypto
```

- **Nordnet**: Portfolio → Transactions → Export (the tab-separated, UTF-16 "per position" format).
- **Firi**: Account → Transaction history → Export CSV. This reconstructs your position from
  the full transaction ledger rather than the live balance endpoint, because Firi's balance
  API excludes anything currently staked (see the module docstring in `import_firi.py` for
  the full story).

## Your data stays local

`.gitignore` already excludes `backend/portfolio.db` (your holdings/watchlist),
`backend/.env` (your `FIRI_API_KEY`), and `backend/certs/windows_ca_bundle.pem` (see below) —
none of them have ever been committed. Forking or cloning this repo gets you the app, not
anyone's data.

For crypto private endpoints, copy `backend/.env.example` to `backend/.env` and fill in
`FIRI_API_KEY` (Firi account → Settings → API). Public ticker/history calls work without it.

## Troubleshooting: SSL certificate errors

If requests to Firi/yfinance/CoinGecko fail with `CERTIFICATE_VERIFY_FAILED: unable to get
local issuer certificate`, some root certificate your OS trusts (often a corporate or
antivirus SSL-inspection cert) isn't in Python's bundled cert list. Regenerate the local,
gitignored bundle `ca_bundle.py` uses:

```powershell
powershell -File backend/certs/generate_ca_bundle.ps1
```

Then restart the server. This is machine-specific by design, which is why the generated
file isn't committed.

## Roadmap / not-yet-decided

- Price charts (TradingView Lightweight Charts is the natural fit for the theme — not wired
  up yet, current focus is the signal table).
- News feed per position.
- Remote access: local-first for now; when ready to check from a phone, put a private tunnel
  (e.g. Tailscale) in front of `uvicorn` rather than exposing it directly.
- More signals (volume spikes, volatility-based position sizing hints).

## License

[MIT](LICENSE)
