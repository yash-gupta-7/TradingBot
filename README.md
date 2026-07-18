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

## Phase 2 — live paper trading and real orders

Run the live paper trader (simulated fills, real market data, no real
orders):

```bash
python -m live.run_paper
```

Open `http://localhost:5050` for the live dashboard.

### Going live (real money, real orders)

`live.run_live` requires **all three** of the following, or it refuses to
start:

1. The `--live` CLI flag.
2. `config.yaml`: `execution.mode: live`
3. `config.yaml`: `execution.confirm_live: true`

```bash
python -m live.run_live --live
```

**Before your first live run**, review `config/config.yaml`:

- `instrument.lot_size` — must match the real SENSEX weekly options lot
  size, not the placeholder value.
- `risk.risk_pct` and `risk.max_daily_loss_pct` — the checked-in values
  are elevated test settings, not real-money position-sizing/loss-limit
  numbers.

### Kill switch

To immediately flatten any open position and halt trading for the rest
of the day, either click "Flatten & Halt" on the dashboard, or run:

```bash
python -m live.kill_switch --port 5050
```

The halt persists across a restart (backed by `db/trades.sqlite3`) —
you must explicitly clear `daily_halt` for the day to resume.

## What's not here yet

- Telegram alerts (Phase 3)
