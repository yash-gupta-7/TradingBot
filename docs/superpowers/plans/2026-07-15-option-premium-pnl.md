# Option-Premium P&L Modeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the backtest's raw index-point P&L proxy with a Black-Scholes-modeled option premium, so trade economics reflect convexity and time decay instead of a linear index-point simulation.

**Architecture:** A new pure-function module, `pricing/black_scholes.py`, provides a standard Black-Scholes premium calculator plus SENSEX-specific helpers (ATM strike selection, next weekly expiry, realized volatility from the index's own returns, time-to-expiry). `backtest/engine.py`'s entry/exit *trigger* logic (SuperTrend, EMA, ADX, ATR, volume, VWAP, ATR-based stop/target) is untouched — it keeps deciding *when* to enter/exit using index technicals. Only the trade's financial outcome changes: at entry the engine now also computes an ATM strike, expiry, and entry premium; at exit it prices the same contract at the exit index level; `Trade.pnl` becomes `(exit_premium - entry_premium) * quantity`.

**Tech Stack:** Python 3.12, pandas, numpy (already in `requirements.txt` — no new dependency; the standard normal CDF is computed via `math.erf`, not `scipy`).

**Design doc:** `docs/superpowers/specs/2026-07-15-option-premium-pnl-design.md`

## Global Constraints

- Real historical option premiums are **not obtainable** from Kite for this backtest window — `kite.instruments("BFO")` only lists contracts with expiry `>= 2026-07-16` (confirmed empirically; zero expired SENSEX option contracts remain listed). All premium values in this plan come from the Black-Scholes model, not fetched market data.
- SENSEX weekly option strike spacing is confirmed as **100 points** from Kite's live instrument dump.
- SENSEX weekly expiry is confirmed as **Thursday 15:30 IST** for the backtest's June–July 2026 window (per user confirmation) — hardcoded, not fetched, since expired contracts aren't in the instrument list to derive it from.
- Risk-free rate is a fixed constant `0.07` inside `pricing/black_scholes.py` — not a `config.yaml` knob (negligible effect over a week-long option life; every other tunable stays in `config.yaml` per this project's existing convention, but this one is a genuine non-varying constant, not a strategy parameter).
- `strategy/strategy.py`, `risk/risk_manager.py`, `backtest/metrics.py`, and all entry/exit trigger logic in `backtest/engine.py` are **out of scope** — do not modify them. Only `Trade`'s P&L calculation and the values feeding `calculate_position_size` change.
- Every step's exact code and expected command output below was verified by actually running it against this repository before this plan was written — if your output differs, stop and re-diagnose rather than assuming the plan is right.

---

## File Structure

```
TradingBot/
├── pricing/                      # NEW package
│   ├── __init__.py                # NEW, empty (matches indicators/__init__.py, risk/__init__.py)
│   └── black_scholes.py           # NEW: BS premium + SENSEX calendar/strike helpers
├── config/
│   └── config.yaml                # MODIFY: add `pricing.realized_vol_window`
├── backtest/
│   └── engine.py                  # MODIFY: Trade dataclass + _enter_trade + _close_trade
├── tests/
│   ├── test_black_scholes.py      # NEW
│   ├── test_engine.py             # MODIFY: CFG gains a `pricing` section
│   └── test_metrics.py            # MODIFY: Trade-construction helper gains new required fields
```

---

### Task 1: Core Black-Scholes premium formula

**Files:**
- Create: `pricing/__init__.py` (empty)
- Create: `pricing/black_scholes.py`
- Test: `tests/test_black_scholes.py`

**Interfaces:**
- Produces: `black_scholes_premium(spot: float, strike: float, time_to_expiry_years: float, volatility: float, option_type: str, risk_free_rate: float = RISK_FREE_RATE) -> float`. `option_type` is `"CE"` or `"PE"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_black_scholes.py`:

```python
import pytest

from pricing.black_scholes import black_scholes_premium


def test_call_premium_matches_textbook_reference():
    # Classic Hull reference case: S=100, K=100, T=1yr, r=5%, sigma=20%
    premium = black_scholes_premium(100, 100, 1.0, 0.2, "CE", risk_free_rate=0.05)
    assert premium == pytest.approx(10.450583572185565)


def test_put_premium_matches_textbook_reference():
    premium = black_scholes_premium(100, 100, 1.0, 0.2, "PE", risk_free_rate=0.05)
    assert premium == pytest.approx(5.573526022256971)


def test_call_premium_at_sensex_scale_with_default_risk_free_rate():
    # ATM, 7 calendar days to expiry, 12% vol, project default r=7%
    premium = black_scholes_premium(75000, 75000, 7 / 365, 0.12, "CE")
    assert premium == pytest.approx(548.8173632590551)


def test_put_premium_at_sensex_scale_with_default_risk_free_rate():
    premium = black_scholes_premium(75000, 75000, 7 / 365, 0.12, "PE")
    assert premium == pytest.approx(448.19998455592577)


def test_call_premium_falls_back_to_intrinsic_value_at_expiry():
    # T=0: no time value, just max(spot - strike, 0)
    premium = black_scholes_premium(105, 100, 0.0, 0.2, "CE")
    assert premium == pytest.approx(5.0)


def test_put_premium_falls_back_to_intrinsic_value_at_expiry():
    premium = black_scholes_premium(105, 100, 0.0, 0.2, "PE")
    assert premium == pytest.approx(0.0)


def test_zero_volatility_does_not_raise_and_stays_near_discounted_intrinsic():
    # volatility=0 must not divide by zero -- clamped to a small floor internally.
    premium = black_scholes_premium(75000, 75000, 7 / 365, 0.0, "CE")
    assert premium == pytest.approx(100.61737870312936)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_black_scholes.py -v`
Expected: `ModuleNotFoundError: No module named 'pricing'` (module doesn't exist yet)

- [ ] **Step 3: Write the implementation**

Create `pricing/__init__.py` (empty file).

Create `pricing/black_scholes.py`:

```python
"""Black-Scholes option premium modeling for the backtest's P&L layer.

Real historical premiums for expired SENSEX weekly contracts aren't
retrievable from Kite (instruments() only lists current/future expiries),
so trade P&L is priced with this model against the real historical index
data instead. Shared, pure-function module -- usable unmodified by Phase 2
live/paper execution later, same pattern as risk/risk_manager.py.
"""
import math

RISK_FREE_RATE = 0.07
_MIN_TIME_TO_EXPIRY_YEARS = 1e-6
_MIN_VOLATILITY = 1e-4


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_premium(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = RISK_FREE_RATE,
) -> float:
    """European option premium. `option_type` is "CE" or "PE". Falls back
    to intrinsic value at/after expiry rather than dividing by a zero
    time-to-expiry."""
    intrinsic = max(spot - strike, 0.0) if option_type == "CE" else max(strike - spot, 0.0)
    if time_to_expiry_years <= _MIN_TIME_TO_EXPIRY_YEARS:
        return intrinsic

    sigma = max(volatility, _MIN_VOLATILITY)
    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma**2) * time_to_expiry_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-risk_free_rate * time_to_expiry_years)

    if option_type == "CE":
        return spot * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    return strike * discount * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_black_scholes.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add pricing/__init__.py pricing/black_scholes.py tests/test_black_scholes.py
git commit -m "feat: add Black-Scholes option premium calculator"
```

---

### Task 2: SENSEX calendar/strike helpers

**Files:**
- Modify: `pricing/black_scholes.py`
- Modify: `tests/test_black_scholes.py`

**Interfaces:**
- Consumes: nothing from Task 1 beyond the module's existing constants.
- Produces:
  - `realized_volatility(close: pd.Series, window: int) -> float`
  - `atm_strike(spot: float, interval: int = 100) -> float`
  - `next_weekly_expiry(timestamp: pd.Timestamp) -> pd.Timestamp`
  - `time_to_expiry_years(now: pd.Timestamp, expiry: pd.Timestamp) -> float`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_black_scholes.py`:

```python
import pandas as pd

from pricing.black_scholes import atm_strike, next_weekly_expiry, realized_volatility, time_to_expiry_years


def test_atm_strike_rounds_to_nearest_100():
    assert atm_strike(75043) == 75000


def test_atm_strike_rounds_half_to_even_at_exact_midpoint():
    # 75050 is exactly between 75000 and 75100; Python's round-half-to-even
    # picks 75000 (750 is the even neighbor). Pinned explicitly since this
    # is a genuine ambiguity, not an arbitrary implementation detail.
    assert atm_strike(75050) == 75000
    assert atm_strike(75150) == 75200


def test_next_weekly_expiry_same_day_before_cutoff():
    ts = pd.Timestamp("2026-07-16 10:00:00+05:30")  # a Thursday
    assert next_weekly_expiry(ts) == pd.Timestamp("2026-07-16 15:30:00+05:30")


def test_next_weekly_expiry_rolls_to_next_week_after_cutoff():
    ts = pd.Timestamp("2026-07-16 16:00:00+05:30")  # same Thursday, after 15:30
    assert next_weekly_expiry(ts) == pd.Timestamp("2026-07-23 15:30:00+05:30")


def test_next_weekly_expiry_from_a_non_thursday():
    ts = pd.Timestamp("2026-07-13 10:00:00+05:30")  # a Monday
    assert next_weekly_expiry(ts) == pd.Timestamp("2026-07-16 15:30:00+05:30")


def test_time_to_expiry_years_is_positive_fraction_of_a_year():
    ts = pd.Timestamp("2026-07-16 10:00:00+05:30")
    expiry = next_weekly_expiry(ts)
    assert time_to_expiry_years(ts, expiry) == pytest.approx(0.0006278538812785388)


def test_time_to_expiry_years_floors_at_zero_when_past_expiry():
    ts = pd.Timestamp("2026-07-16 16:00:00+05:30")
    expiry = pd.Timestamp("2026-07-16 15:30:00+05:30")  # already passed
    assert time_to_expiry_years(ts, expiry) == 0.0


def test_realized_volatility_is_zero_on_a_constant_series():
    close = pd.Series([100.0] * 10)
    assert realized_volatility(close, window=5) == 0.0


def test_realized_volatility_is_zero_on_a_single_bar_series():
    close = pd.Series([100.0])
    assert realized_volatility(close, window=5) == 0.0


def test_realized_volatility_on_a_known_alternating_series():
    close = pd.Series([100.0, 101.0, 100.0, 101.0, 100.0, 101.0])
    assert realized_volatility(close, window=5) == pytest.approx(3.3507656043840948)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/test_black_scholes.py -v`
Expected: the 7 tests from Task 1 pass; the new ones fail with `ImportError: cannot import name 'atm_strike'` (functions don't exist yet)

- [ ] **Step 3: Write the implementation**

Add to `pricing/black_scholes.py` (after the existing imports, extend them; add the constants and functions at module level):

```python
import numpy as np
import pandas as pd
```

(add these two imports alongside the existing `import math` at the top of the file)

```python
_EXPIRY_WEEKDAY = 3  # Thursday (Monday=0 ... Sunday=6)
_EXPIRY_HOUR, _EXPIRY_MINUTE = 15, 30
_MINUTES_PER_YEAR = 375 * 252  # ~375 trading minutes/day, ~252 trading days/year


def realized_volatility(close: pd.Series, window: int) -> float:
    """Annualized realized volatility from trailing log returns of the
    last `window` bars of a 1-minute close series. Returns 0.0 if there's
    not enough history for at least 2 returns."""
    tail = close.iloc[-window - 1 :]
    log_returns = np.log(tail / tail.shift(1)).dropna()
    if len(log_returns) < 2:
        return 0.0
    return float(log_returns.std() * math.sqrt(_MINUTES_PER_YEAR))


def atm_strike(spot: float, interval: int = 100) -> float:
    """Nearest strike to spot, rounded to `interval` (100 for SENSEX
    weekly options, confirmed from Kite's live strike list)."""
    return round(spot / interval) * interval


def next_weekly_expiry(timestamp: pd.Timestamp) -> pd.Timestamp:
    """Next Thursday 15:30 at or after `timestamp` (confirmed expiry
    weekday for the backtest window; a Thursday entry before 15:30
    expires same-day)."""
    days_ahead = (_EXPIRY_WEEKDAY - timestamp.weekday()) % 7
    expiry = (timestamp.normalize() + pd.Timedelta(days=days_ahead)).replace(
        hour=_EXPIRY_HOUR, minute=_EXPIRY_MINUTE
    )
    if expiry < timestamp:
        expiry += pd.Timedelta(weeks=1)
    return expiry


def time_to_expiry_years(now: pd.Timestamp, expiry: pd.Timestamp) -> float:
    """Calendar-time fraction of a year between `now` and `expiry`,
    floored at 0 (never negative)."""
    seconds = max((expiry - now).total_seconds(), 0.0)
    return seconds / (365 * 24 * 3600)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/test_black_scholes.py -v`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add pricing/black_scholes.py tests/test_black_scholes.py
git commit -m "feat: add SENSEX strike/expiry/volatility helpers to pricing module"
```

---

### Task 3: Wire premium pricing into the backtest engine

**Files:**
- Modify: `config/config.yaml`
- Modify: `backtest/engine.py`
- Modify: `tests/test_engine.py`
- Modify: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `black_scholes_premium`, `atm_strike`, `next_weekly_expiry`, `realized_volatility`, `time_to_expiry_years` from `pricing.black_scholes` (Tasks 1-2). `calculate_position_size` from `risk.risk_manager` (unchanged signature: `(capital, risk_pct, entry_price, stop_price, lot_size) -> int`, works unmodified since it's generic about what "price" means).
- Produces: `Trade` dataclass now has `strike: float`, `option_type: str`, `entry_premium: float`, `volatility: float`, `expiry: pd.Timestamp`, `exit_premium: float | None` in addition to its existing fields. `Trade.pnl` is `(exit_premium - entry_premium) * quantity`.

- [ ] **Step 1: Add the `pricing` config section**

In `config/config.yaml`, after the `backtest:` section at the end of the file, add:

```yaml

pricing:
  realized_vol_window: 60
```

- [ ] **Step 2: Update `Trade` dataclass and its `pnl` property**

In `backtest/engine.py`, replace the imports block and `Trade` class:

```python
from backtest.data_loader import resample_to_5min
from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend
from pricing.black_scholes import (
    atm_strike,
    black_scholes_premium,
    next_weekly_expiry,
    realized_volatility,
    time_to_expiry_years,
)
from risk.risk_manager import (
    TrailingStopTracker,
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
)
from strategy.strategy import generate_signal


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str
    entry_price: float
    quantity: int
    stop_price: float
    target_price: float
    strike: float
    option_type: str
    entry_premium: float
    volatility: float
    expiry: pd.Timestamp
    entry_reasons: list[str] = field(default_factory=list)
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_premium: float | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float | None:
        if self.exit_premium is None:
            return None
        return (self.exit_premium - self.entry_premium) * self.quantity
```

This replaces the file's existing `from backtest.data_loader ...` through `from strategy.strategy import generate_signal` import block, and the existing `@dataclass class Trade: ...` block (through the old `pnl` property that used `mult = 1 if self.direction == "BUY_CALL" else -1`).

- [ ] **Step 3: Price the premium at entry and size position off premium risk**

In `backtest/engine.py`, replace the `_enter_trade` method:

```python
    def _enter_trade(self, window_1m: pd.DataFrame, signal) -> None:
        entry_time = window_1m.index[-1]
        entry_price = window_1m["close"].iloc[-1]
        prev_candle = window_1m.iloc[-2]
        atr_value = calculate_atr(window_1m, self.cfg["indicators"]["atr_length"]).iloc[-1]
        stop_price = calculate_stop_loss(
            signal.direction, prev_candle, atr_value, self.cfg["risk"]["atr_stop_multiplier"], entry_price
        )

        option_type = "CE" if signal.direction == "BUY_CALL" else "PE"
        strike = atm_strike(entry_price)
        expiry = next_weekly_expiry(entry_time)
        volatility = realized_volatility(window_1m["close"], self.cfg["pricing"]["realized_vol_window"])
        entry_ttm = time_to_expiry_years(entry_time, expiry)
        entry_premium = black_scholes_premium(entry_price, strike, entry_ttm, volatility, option_type)
        stop_premium = black_scholes_premium(stop_price, strike, entry_ttm, volatility, option_type)

        qty = calculate_position_size(
            self.capital, self.cfg["risk"]["risk_pct"], entry_premium, stop_premium, self.cfg["instrument"]["lot_size"]
        )
        if qty <= 0:
            return
        target_price = calculate_target(signal.direction, entry_price, stop_price, self.cfg["risk"]["reward_risk_ratio"])

        self.open_trade = Trade(
            entry_time=entry_time,
            direction=signal.direction,
            entry_price=entry_price,
            quantity=qty,
            stop_price=stop_price,
            target_price=target_price,
            strike=strike,
            option_type=option_type,
            entry_premium=entry_premium,
            volatility=volatility,
            expiry=expiry,
            entry_reasons=signal.reasons,
        )
        self.tracker = TrailingStopTracker(
            signal.direction, entry_price, stop_price, self.cfg["risk"]["breakeven_r"], self.cfg["risk"]["trail_start_r"]
        )
        self.trades_today += 1
```

Note: `option_type` is `"PE"` for a `SELL_PUT` signal — the engine always **buys** an option (a bearish view buys a put), even though the signal label itself (defined in `strategy.py`, out of scope here) still says `SELL_PUT`.

- [ ] **Step 4: Price the premium at exit**

In `backtest/engine.py`, replace the `_close_trade` method's opening lines (everything stays the same after `self.trades.append(self.open_trade)`):

```python
    def _close_trade(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        self.open_trade.exit_time = exit_time
        self.open_trade.exit_price = exit_price
        self.open_trade.exit_reason = reason
        exit_ttm = time_to_expiry_years(exit_time, self.open_trade.expiry)
        self.open_trade.exit_premium = black_scholes_premium(
            exit_price, self.open_trade.strike, exit_ttm, self.open_trade.volatility, self.open_trade.option_type
        )
        self.trades.append(self.open_trade)
```

- [ ] **Step 5: Add the `pricing` section to `test_engine.py`'s CFG fixture**

In `tests/test_engine.py`, find:

```python
    "trading_hours": {"windows": [["09:15", "15:30"]], "square_off_time": "15:20"},
    "backtest": {"initial_capital": 100000, "warmup_bars": 60},
}
```

Replace with:

```python
    "trading_hours": {"windows": [["09:15", "15:30"]], "square_off_time": "15:20"},
    "backtest": {"initial_capital": 100000, "warmup_bars": 60},
    "pricing": {"realized_vol_window": 60},
}
```

(`CFG_HALT = {**CFG, ...}` further down in the same file inherits this automatically — no separate edit needed there.)

- [ ] **Step 6: Update `test_metrics.py`'s `Trade`-construction helper**

`compute_metrics` only reads `t.pnl`; these tests hand-pick specific P&L values via `entry_price`/`exit_price` and don't care about option pricing. Feed the same numbers into the new premium fields so every existing assertion in this file keeps its exact expected value.

In `tests/test_metrics.py`, replace the `_trade` helper:

```python
def _trade(entry_time, exit_time, direction, entry_price, exit_price, qty=20):
    # entry_premium/exit_premium reuse the same numbers as entry_price/exit_price
    # so pnl == exit_price - entry_price, matching every comment below -- these
    # tests are about compute_metrics's arithmetic, not option pricing.
    return Trade(
        entry_time=pd.Timestamp(entry_time),
        direction=direction,
        entry_price=entry_price,
        quantity=qty,
        stop_price=entry_price - 10 if direction == "BUY_CALL" else entry_price + 10,
        target_price=entry_price + 20 if direction == "BUY_CALL" else entry_price - 20,
        strike=entry_price,
        option_type="CE" if direction == "BUY_CALL" else "PE",
        entry_premium=entry_price,
        volatility=0.15,
        expiry=pd.Timestamp(entry_time) + pd.Timedelta(days=7),
        exit_time=pd.Timestamp(exit_time),
        exit_price=exit_price,
        exit_premium=exit_price,
        exit_reason="target_hit",
    )
```

- [ ] **Step 7: Run the full test suite**

Run: `python -m pytest tests/ -q`
Expected: `63 passed` (60 pre-existing across the rest of the suite, minus the 2 already-updated fixtures counted in that total, plus the 17 new `test_black_scholes.py` tests from Tasks 1-2 — no test outside `test_engine.py`/`test_metrics.py` needs any change; every exact-value assertion in `test_engine.py` (including `test_engine_halts_after_max_consecutive_losses`'s `len(uncapped) == 3`, `len(trades) == 2`, and `all(t.pnl < 0 ...)`) passes unmodified against the new premium-based P&L)

If any test in `test_engine.py` fails here: inspect the actual trade count/pnl output with a quick `print`, don't guess — the crash fixtures were designed to produce unambiguous adverse index moves immediately after entry, so a real loss in premium terms is expected, but if the specific magnitude tuned into a fixture happens to sit right at a boundary, adjust that fixture's `crash_step`/`down_step` constant (not the assertion) to restore a clear margin, and re-run.

- [ ] **Step 8: Manually verify against real Kite data**

Run: `python -m backtest.run_backtest --from 2026-06-01 --to 2026-07-01`

Expected output (verified while writing this plan):

```
Trades: 62
{
  "win_rate": 0.3225806451612903,
  "profit_factor": 0.7404939694875015,
  ...
}
```

Exact figures may drift slightly if Kite's historical data for this range has since been revised, but the trade count should be in this range (not 0, not wildly different) and `win_rate`/`profit_factor` should reflect genuine premium decay — e.g. a materially different (usually lower) win rate than a same-day comparison run against the pre-this-plan index-point P&L would have shown.

- [ ] **Step 9: Commit**

```bash
git add config/config.yaml backtest/engine.py tests/test_engine.py tests/test_metrics.py
git commit -m "feat: price backtest trade P&L with Black-Scholes option premiums"
```

---

## Self-Review Notes

- **Spec coverage:** every component in the design doc (`black_scholes_premium`, `realized_volatility`, `atm_strike`, `next_weekly_expiry`, `Trade` field additions, `_enter_trade`/`_close_trade` premium wiring, position sizing off premium distance) has a corresponding step above. The design's explicit "out of scope" items (real historical premium fetching, bid/ask/slippage modeling, `SELL_PUT`→`BUY_PUT` renaming, non-Thursday historical expiry calendars) are correctly not touched by any task.
- **Placeholder scan:** no TBDs; every code step is complete, runnable code copied from an implementation that was actually executed against this repository (all 63 tests passed, the real CLI run produced the numbers shown in Task 3 Step 8).
- **Type/signature consistency:** `black_scholes_premium`'s parameter order and `option_type` string values (`"CE"`/`"PE"`) are identical everywhere they're called across Tasks 1-3. `Trade`'s new field names (`strike`, `option_type`, `entry_premium`, `volatility`, `expiry`, `exit_premium`) match between the dataclass definition (Task 3 Step 2) and both call sites that construct/mutate it (Task 3 Steps 3-4) and the test helper (Task 3 Step 6).
