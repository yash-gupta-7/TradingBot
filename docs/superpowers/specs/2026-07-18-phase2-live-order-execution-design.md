# Phase 2 — Live Order Execution — Design

## Problem

`live/paper_engine.py` already runs the full signal engine live against
real Kite websocket ticks, resolves the real ATM SENSEX weekly option
contract for display (`_get_atm_option`), and serves a live dashboard
(`live/api.py`, `live/dashboard.html`). But it never places a real order —
every entry/exit is simulated in-memory, priced off the SENSEX index level
(`Trade.pnl` in `backtest/engine.py`), and state survives a restart only
via a self-trusted local file (`.paper_state.json`) that is never checked
against what the broker actually holds.

To trade real money, the bot needs to actually place, track, and reconcile
real orders on Kite — and do so with guarantees a JSON file blindly
trusting its own last write can't give: a rejected order must not be
silently treated as a fill, a crash mid-trade must not lose track of an
open real position, and a restart must not quietly reset loss limits.

## Goal

Add real order placement for the existing signal/risk logic, without
changing how entries or exits are *decided* (index price, indicators,
stop/target/trailing stay exactly as they are in `PaperEngine` today).
Paper mode remains the default and is untouched in behavior; live mode is
strictly additive and gated behind multiple explicit opt-ins.

## Scope boundary

**Unchanged:** `strategy.generate_signal()`, `risk/risk_manager.py`
(position sizing, stop/target/trailing — reused unmodified per its own
docstring), all of `backtest/`, and the index-price-based entry/exit
decision logic currently in `PaperEngine._check_entry` /
`_manage_tick` / `_check_closed_bar_exits`. The option-premium
Black-Scholes work (`docs/superpowers/specs/2026-07-15-option-premium-pnl-design.md`)
is a separate, independent effort for backtest realism and is not touched
or depended on here — live mode prices real fills from real broker orders,
not a model.

**Changed:** how a decided entry/exit becomes a real position — order
placement, fill confirmation, restart recovery, and daily-loss-limit
persistence for live trading only. Paper mode's existing
`.paper_state.json` mechanism is left as-is; it is not real money and
doesn't need broker reconciliation.

## Design

### `execution/order_manager.py` — new module

Two classes sharing one interface, so the engine that decides *when* to
trade never knows which is underneath:

- `submit_entry(option_symbol: str, quantity: int) -> Fill` — always a BUY
  (both `BUY_CALL` and `SELL_PUT` signals buy an option; see
  `_get_atm_option`'s existing `opt_type` mapping).
- `submit_exit(option_symbol: str, quantity: int) -> Fill` — always a SELL
  to close.
- `Fill`: `{status: "filled" | "rejected", price: float | None, order_id: str | None}`.

`PaperOrderManager` is `PaperEngine`'s current simulated-fill behavior
(fills instantly at the requested price), extracted unchanged so paper
mode's behavior doesn't shift by a cent.

`LiveOrderManager(kite)`:
- Places `kite.place_order(variety="regular", exchange="BFO",
  tradingsymbol=option_symbol, transaction_type=BUY|SELL,
  quantity=quantity, order_type="MARKET", product="MIS")`.
- Polls `kite.order_history(order_id)` for a terminal status
  (`COMPLETE`/`REJECTED`/`CANCELLED`), backing off up to a bounded total
  wait (e.g. 1s, 2s, 3s… capped at ~15s total).
- Entry rejected/timed out → returns `Fill(status="rejected", ...)`;
  `PaperEngine` (see below) treats this as "no trade happened", logs it,
  and does not fabricate a position.
- Exit rejected/timed out → this is the dangerous case (a real open
  position the bot can no longer confirm is closed). Retries the SELL a
  bounded number of times with a fresh order each attempt; if still
  unresolved, logs at highest severity and leaves `open_trade` in a
  `needs_manual_attention` state rather than silently dropping it or
  looping forever.
- On COMPLETE, the fill price is `average_price` from the order history —
  this becomes the trade's real `option_entry_price`/`option_exit_price`,
  replacing today's separate `kite.quote()` call for display purposes.

### `PaperEngine` changes

`PaperEngine.__init__` gains an `order_manager: OrderManager` parameter
(constructed by the caller — `run_paper.py` passes `PaperOrderManager()`,
new `run_live.py` passes `LiveOrderManager(kite)`). `_enter_trade` and
`_close_trade` call `self.order_manager.submit_entry(...)` /
`submit_exit(...)` at the point where they currently call
`_get_atm_option` / set `exit_price`, and only proceed to build/update the
`Trade` record if the returned `Fill.status == "filled"`. No other method
changes. (A rename away from `PaperEngine` is out of scope — cosmetic,
not load-bearing — but is worth a quick pass to avoid the class name
`PaperEngine` running real trades, e.g. `TradingEngine` with `mode` as
metadata on the instance. Deferred to the implementation plan to decide.)

### `db/trades.py` + `db/trades.sqlite3` — new SQLite trade log

One `trades` table: `id, mode (paper|live), entry_time, exit_time,
direction, option_symbol, index_entry_price, index_exit_price,
option_entry_price, option_exit_price, quantity, stop_price,
target_price, exit_reason, pnl`. A row is inserted on entry (no exit
fields yet) and updated on exit. Both modes write here — paper mode gains
a queryable trade history/daily-summary source as a side effect, at no
extra cost.

**Live-mode startup uses this table, not `.paper_state.json`**, to rebuild
`trades_today`, `consecutive_losses`, `day_start_capital`, and
`trading_halted_today` for the current calendar day: `SELECT * FROM
trades WHERE mode='live' AND date(entry_time) = today`. This is the
mechanism that survives a crash without losing loss-limit state.

### Startup reconciliation (`run_live.py`, live mode only)

Before entering the tick loop:
1. Rebuild today's halt-state counters from SQLite (above).
2. Query `kite.positions()["net"]`, filtered to the configured
   BFO/SENSEX instrument.
3. **Nonzero position + a matching open row in SQLite** (same
   `option_symbol`, no `exit_time`) → rebuild `self.open_trade` (entry
   price/qty/stop/target from the SQLite row) and `self.tracker`
   (recomputed via `TrailingStopTracker`'s normal constructor using the
   stored stop) and resume monitoring on the next tick. No new entry is
   placed while this reconciliation is pending.
4. **Nonzero position with no matching open row** (e.g. a manual order
   placed outside the bot) → log at highest severity, do not touch it,
   and refuse to start automated entries until the operator resolves it
   (matches the earlier decision: reconcile the routine case
   automatically, don't invent recovery logic for the out-of-band case).
5. **Zero position** → normal cold start, proceed as today.

### Safety gates

- `run_paper.py` is unchanged and never touches `LiveOrderManager`.
- New `run_live.py` is the only entry point that can construct a
  `LiveOrderManager`. It requires **all** of: the CLI is invoked with
  `--live`, `config.yaml`'s new `execution.mode: live`, and
  `execution.confirm_live: true`. Any one missing → refuses to start
  with a clear error naming which gate failed. (`execution.mode` /
  `confirm_live` default to `paper` / `false` in the checked-in config.)
- Kill switch: `POST /api/kill` (new endpoint in `live/api.py`) and a
  `python -m live.kill_switch` CLI both do the same thing — if
  `open_trade` is set, call `order_manager.submit_exit(...)` immediately,
  then set `trading_halted_today = True` and persist it (a SQLite update
  for live mode) so a subsequent restart stays halted for the rest of the
  day. Independent of the automatic consecutive-loss/daily-loss halts —
  this is a manual override.

### Pre-flight checklist (documentation only, not code)

`config.yaml` currently has `risk.risk_pct: 10.0`, `risk.max_daily_loss_pct:
35.0`, and `instrument.lot_size: 20` — all marked or known as
test/placeholder values. The Phase 2 README addition will call these out
explicitly as required-before-first-live-trade config, since they directly
control real-money position sizing and halt thresholds.

## Testing

- `tests/test_order_manager.py`: `LiveOrderManager` against a mocked
  `kite` client — successful fill, rejection, timeout with no terminal
  status, exit-side rejection triggering the manual-attention state.
  `PaperOrderManager` — confirms identical behavior to today's inline
  `PaperEngine` fill logic (regression guard for the extraction).
- `tests/test_reconciliation.py`: mocked `kite.positions()` + a SQLite
  fixture — matching open trade rebuilds correctly; no-match position logs
  and blocks entries; zero-position cold start is a no-op.
- `tests/test_trades_db.py`: insert-on-entry/update-on-exit round-trip,
  and halt-state rebuild from a fixture day's rows (mix of wins/losses
  crossing `max_consecutive_losses` and `max_daily_loss_pct` thresholds).
- `tests/test_kill_switch.py`: with an open trade, confirms
  `submit_exit` is called and halt persists; with no open trade, confirms
  it's a pure halt with no order placed.
- No automated test places a real order against Kite. First real-money run
  is a manual, documented checklist (small size, market hours, operator
  watching the dashboard) — out of scope for this spec, called out as a
  follow-up doc if wanted.
