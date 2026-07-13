# SENSEX Weekly Options Bot — Phase 1 (Signal Engine & Backtester)

Phase 1 of 3. This phase contains the indicator/strategy/risk logic and a
backtester against real Kite historical data. **No live orders are placed
in this phase** — that's Phase 2.

## Setup

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in `KITE_API_KEY` / `KITE_API_SECRET`
   from your Kite Connect app (https://developers.kite.trade/apps).
4. Review `config/config.yaml` — in particular set `instrument.lot_size` to
   the current real SENSEX weekly options lot size.

## Daily login (required before any historical fetch — Kite tokens expire daily)

```bash
python -m kite.login
```

## Run the test suite

```bash
pytest -v
```

## Run a backtest

```bash
python -m backtest.run_backtest --from 2026-06-01 --to 2026-07-01
```

Prints trade count and performance metrics (win rate, profit factor, max
drawdown, Sharpe ratio, average trade, expectancy, monthly returns, max
consecutive wins/losses).

## What's not here yet

- Live/paper order execution, order manager, retry/reconciliation logic (Phase 2)
- SQLite trade logging, daily summary reports (Phase 2)
- Telegram alerts (Phase 3)
- Live dashboard (Phase 3)
- Daily halt state persisted across process restarts — the backtest engine's
  daily-loss/consecutive-loss halt logic will be reused by Phase 2's live
  risk manager, but live trading needs it to survive a bot restart mid-day,
  which this phase doesn't need.
