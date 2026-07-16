# Option-Premium P&L Modeling — Design

## Problem

`BacktestEngine` currently prices every trade as a raw SENSEX index-point
move: `Trade.pnl = (exit_price - entry_price) * direction_mult * quantity`,
where `entry_price`/`exit_price` are index closes. This is a linear,
delta-1, zero-decay proxy for what is actually a SENSEX **weekly options**
strategy (per `config.yaml`'s `instrument.lot_size` comment and the
`BUY_CALL`/`SELL_PUT` signal labels). It ignores premium convexity and time
decay entirely, so backtest win rate/expectancy is not comparable to real
option trading (manual or otherwise).

Real historical option premiums cannot be substituted directly: Kite's
`instruments("BFO")` dump only retains **currently/future-listed**
contracts (confirmed empirically — zero SENSEX option contracts with
expiry before 2026-07-15 remain listed as of this writing). Expired weekly
contracts have no discoverable `instrument_token`, so `historical_data()`
cannot be called for them regardless of date range. Real premiums for past
backtest windows are therefore unobtainable via Kite, full stop.

## Goal

Replace the index-point P&L proxy with a Black-Scholes-modeled option
premium, computed from real historical index prices (which Kite does
provide), so backtest economics include convexity and time decay instead
of a linear proxy.

## Scope boundary

**Unchanged:** `strategy.generate_signal()` (entry trigger), and all exit
triggers in `BacktestEngine._manage_open_trade` (target/stop hit via
index-based ATR/SuperTrend levels, SuperTrend reversal, EMA reversal, EOD
square-off). These all continue to operate purely on index technicals —
that is the Phase 1 signal engine and is out of scope here.

**Changed:** only the *financial outcome* of a trade — what premium was
paid/received, and how position size is derived from risk — moves from
index points to a modeled option premium.

## Design

### New module: `pricing/black_scholes.py`

Shared, pure-function module (same pattern as `risk_manager.py`: usable
unmodified by Phase 2 live/paper execution later).

- `black_scholes_premium(spot, strike, time_to_expiry_years, volatility, risk_free_rate, option_type) -> float`
  Standard Black-Scholes-Merton premium for a European call (`"CE"`) or
  put (`"PE"`). `time_to_expiry_years` clamped to a small positive epsilon
  floor to avoid div-by-zero at/after expiry (returns intrinsic value in
  that limit).
- `realized_volatility(close: pd.Series, window: int) -> float`
  Annualized realized volatility from trailing log returns of the index
  close series already present in the fetched 1-minute data. No external
  IV data source needed.
- `atm_strike(spot: float, interval: int = 100) -> float`
  Nearest strike to spot, rounded to the nearest `interval`. `100` is
  SENSEX's confirmed live strike spacing.
- `next_weekly_expiry(timestamp: pd.Timestamp) -> pd.Timestamp`
  Next Thursday at 15:30 IST at or after `timestamp` (confirmed expiry
  weekday for the June–July 2026 backtest window; same-day entries before
  15:30 on a Thursday expire same-day).

Risk-free rate is a fixed 7% constant in this module (negligible effect
over a week-long option life; not exposed as a config knob — revisit only
if a use case needs it).

### `backtest/engine.py` changes

- `Trade` dataclass gains: `strike: float`, `option_type: str` (`"CE"`/`"PE"`),
  `entry_premium: float`, `exit_premium: float | None`. Existing
  `entry_price`/`exit_price` (index levels) are kept as-is for
  debugging/traceability, just no longer used for `pnl`.
- `_enter_trade`: after the existing index-based stop/target/qty
  calculation, additionally:
  - `option_type = "CE" if signal.direction == "BUY_CALL" else "PE"` — a
    bearish view buys a put (a real long-option bearish bet), rather than
    literally selling a put (which is a bullish/neutral trade in real
    options). The `SELL_PUT` signal label is kept unchanged (it's
    `strategy.py`'s directional name, out of scope here) but the engine
    always **buys** an option regardless of direction.
  - `strike = atm_strike(entry_price)`, `expiry = next_weekly_expiry(entry_time)`,
    `vol = realized_volatility(window_1m["close"], cfg["pricing"]["realized_vol_window"])`
    — frozen for the life of the trade (not recomputed at exit), so the
    trade's modeled premium curve doesn't jump from a vol-regime change
    mid-trade. New `config.yaml` section:
    ```yaml
    pricing:
      realized_vol_window: 60  # 1-minute bars, matches existing warmup_bars convention
    ```
  - `entry_premium = black_scholes_premium(entry_price, strike, ttm, vol, r, option_type)`.
  - Position sizing: compute `stop_premium` the same way at the
    already-determined index `stop_price` (same strike/expiry/frozen vol,
    same-instant ttm), then call `calculate_position_size` with
    `entry_premium`/`stop_premium` in place of `entry_price`/`stop_price`
    — risk-in-rupees is now sized off premium movement, which is the real
    risk, not index-point movement.
- `_close_trade`: given the index `exit_price` an existing trigger already
  decided on, compute `exit_premium = black_scholes_premium(exit_price, strike, ttm_at_exit, vol, r, option_type)`
  using the trade's frozen strike/expiry/vol and fresh time-to-expiry.
- `Trade.pnl`: `(exit_premium - entry_premium) * quantity` — no direction
  multiplier needed since every trade is now long an option (buying calls
  or puts is symmetric in P&L sign).

### Testing

- `tests/test_black_scholes.py`: `black_scholes_premium` against known
  reference values (e.g. compare to a textbook/online BS calculator
  output for a fixed input set); `atm_strike` rounding at/away from a
  strike boundary; `next_weekly_expiry` on a Thursday before/after 15:30,
  and on non-Thursday days; `realized_volatility` on a constant series
  (→ ~0) and a known-stdev synthetic series.
- `tests/test_engine.py`: update/add a fixture proving decay is now
  modeled — e.g. a trade where the index round-trips back to its entry
  price (net-zero index move) held for a meaningful chunk of time should
  show a small **loss** from theta decay, not exactly zero P&L as the old
  linear model would.
- Existing `test_risk_manager.py`, `test_strategy.py` tests are unaffected
  (those modules are untouched).

## Out of scope (explicitly not doing)

- Fetching or approximating real historical implied volatility from any
  external vendor — realized volatility from the index itself is the
  agreed approximation.
- Modeling bid/ask spread, liquidity, or slippage on the option premium.
- Changing `strategy.py`'s `SELL_PUT` label to `BUY_PUT` — noted as a
  naming mismatch against real options terminology, but renaming ripples
  into `strategy.py` and its tests for a cosmetic gain; not addressed
  here.
- A full historical trading-calendar (expiry day-of-week is assumed
  constant at Thursday for the backtest window; would need revisiting for
  older backtest ranges where BSE's expiry day rules differed).
