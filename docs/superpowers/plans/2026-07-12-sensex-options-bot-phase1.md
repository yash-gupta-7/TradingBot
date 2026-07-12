# SENSEX Options Bot — Phase 1: Signal Engine & Backtester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and backtest the SENSEX weekly-options signal engine (7 indicators, entry/exit rules, risk sizing, trailing stop) against real Kite historical data, with zero live order placement. This is Phase 1 of 3; Phase 2 (live/paper execution, order manager, DB trade logging) and Phase 3 (Telegram, dashboard, daily risk halts) are separate plans written after this one ships and is validated.

**Architecture:** Pure-function indicator modules (pandas/numpy, no external TA library — avoids `pandas_ta`'s known breakage on numpy>=1.24) feed a `strategy.generate_signal()` that evaluates the full entry rule set on closed candles only. A `risk_manager` module (position sizing, stop selection, trailing tracker) is shared by the backtester now and will be reused unchanged by live execution in Phase 2. `backtest.engine.BacktestEngine` walks 1-minute historical bars forward (never looking ahead), simulating entries/exits with the same risk module, and `backtest.metrics` reports the standard performance stats.

**Tech Stack:** Python 3.12, pandas, numpy, `kiteconnect` (historical data only in this phase), PyYAML, python-dotenv, pytest.

## Global Constraints

- No live order placement anywhere in this phase — `execution/`, `database/`, `utils/telegram.py` do not exist yet; they are Phase 2/3.
- All indicator/strategy functions take explicit typed parameters (DataFrames, floats, ints) — never a raw config dict — so they stay unit-testable in isolation. Config values are read once at the call site (backtest engine / CLI) and passed in.
- Every DataFrame passed to a signal function contains only **closed** candles — the last row is treated as the most recently closed bar. This is how "candle closes before entry" (spec) is satisfied structurally: nothing ever peeks at an in-progress bar.
- **Assumption (EMA lengths):** the spec's "EMA 15 / Smoothing Length = 9" is a TradingView UI artifact (an internal smoothing sub-setting, not the MA period) — both EMAs list `Smoothing Length = 9` because that's the widget default, not because both periods are 9. Implemented as EMA(9) and EMA(15) by period, since "EMA 9 crosses EMA 15" is meaningless otherwise.
- **Assumption (5-min "trend"):** the spec doesn't define a separate higher-timeframe indicator set, so the 5-minute trend filter reuses the same dual-SuperTrend(10,1)/(10,3) agreement check, evaluated on 5-minute bars.
- **Assumption (stop-loss "larger"):** "if ATR stop is larger than previous-candle stop, use ATR stop" is read as: always take whichever stop is **further from entry** (more room, less premature stop-out) — i.e. `min()` of the two stop prices for a long, `max()` for a short. ATR stop multiplier defaults to 1.5x ATR (not specified in the source spec) and is configurable.
- Lot size for SENSEX weekly options is a placeholder in `config.yaml` (`instrument.lot_size`) — must be corrected to the live exchange lot size before Phase 2 places any order.
- Every configurable parameter lives in `config/config.yaml`. No hardcoded thresholds in indicator/strategy/risk code.
- Kite API credentials are read from `.env` (via `python-dotenv`), never committed. `.env.example` documents the required keys.

---

## File Structure

```
TradingBot/
├── config/
│   └── config.yaml
├── kite/
│   ├── __init__.py
│   ├── auth.py              # KiteConnect client + access-token loading
│   └── login.py             # one-off CLI script: daily login flow
├── indicators/
│   ├── __init__.py
│   ├── ema.py
│   ├── rsi.py
│   ├── atr.py
│   ├── adx.py
│   ├── supertrend.py
│   ├── volume.py
│   └── vwap.py
├── strategy/
│   ├── __init__.py
│   └── strategy.py
├── risk/
│   ├── __init__.py
│   └── risk_manager.py
├── backtest/
│   ├── __init__.py
│   ├── data_loader.py
│   ├── engine.py
│   ├── metrics.py
│   └── run_backtest.py      # CLI entry point
├── utils/
│   ├── __init__.py
│   └── config.py
├── tests/
│   ├── __init__.py
│   ├── test_ema.py
│   ├── test_rsi.py
│   ├── test_atr.py
│   ├── test_adx.py
│   ├── test_supertrend.py
│   ├── test_volume.py
│   ├── test_vwap.py
│   ├── test_strategy.py
│   ├── test_risk_manager.py
│   ├── test_data_loader.py
│   ├── test_engine.py
│   └── test_metrics.py
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config/config.yaml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `indicators/__init__.py`, `strategy/__init__.py`, `risk/__init__.py`, `backtest/__init__.py`, `utils/__init__.py`, `kite/__init__.py`, `tests/__init__.py` (all empty)
- Create: `utils/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: str = "config/config.yaml") -> dict` — used by every later CLI/engine entry point.

- [ ] **Step 1: Write requirements.txt**

```
pandas>=2.2
numpy>=1.26
kiteconnect>=5.0.1
PyYAML>=6.0
python-dotenv>=1.0
pytest>=8.0
```

- [ ] **Step 2: Write config/config.yaml**

```yaml
instrument:
  index_symbol: "SENSEX"
  exchange: "BSE"
  lot_size: 20  # PLACEHOLDER — set to the real SENSEX weekly options lot size before live use

timeframes:
  primary: "minute"
  higher: "5minute"

indicators:
  supertrend_fast:
    length: 10
    multiplier: 1
  supertrend_slow:
    length: 10
    multiplier: 3
  ema_fast_length: 9
  ema_slow_length: 15
  ema_slope_lookback: 3
  ema_slope_threshold: 0.05
  rsi_length: 14
  rsi_midline: 50
  rsi_overbought: 80
  rsi_oversold: 20
  adx_length: 14
  adx_threshold: 25
  atr_length: 14
  atr_sma_length: 14
  volume_lookback: 20
  volume_multiplier: 1.5

risk:
  risk_pct: 1.0
  reward_risk_ratio: 2.0
  atr_stop_multiplier: 1.5
  breakeven_r: 1.0
  trail_start_r: 1.5
  max_trades_per_day: 5
  max_consecutive_losses: 3
  max_daily_loss_pct: 2.0

trading_hours:
  windows:
    - ["09:25", "11:30"]
    - ["13:30", "15:00"]
  square_off_time: "15:20"

backtest:
  initial_capital: 100000
  warmup_bars: 60
```

- [ ] **Step 3: Write .env.example**

```
KITE_API_KEY=
KITE_API_SECRET=
KITE_ACCESS_TOKEN_FILE=kite/.access_token
```

- [ ] **Step 4: Write .gitignore**

```
__pycache__/
*.pyc
.env
kite/.access_token
.venv/
*.egg-info/
```

- [ ] **Step 5: Create empty package init files**

```bash
touch indicators/__init__.py strategy/__init__.py risk/__init__.py backtest/__init__.py utils/__init__.py kite/__init__.py tests/__init__.py
```

- [ ] **Step 6: Write utils/config.py**

```python
"""Load the project's single YAML config file."""
from pathlib import Path
import yaml


def load_config(path: str = "config/config.yaml") -> dict:
    with open(Path(path), "r") as f:
        return yaml.safe_load(f)
```

- [ ] **Step 7: Write the failing test**

```python
# tests/test_config.py
from utils.config import load_config


def test_load_config_returns_expected_sections():
    cfg = load_config("config/config.yaml")
    assert "instrument" in cfg
    assert "indicators" in cfg
    assert "risk" in cfg
    assert cfg["risk"]["reward_risk_ratio"] == 2.0
```

- [ ] **Step 8: Run test to verify it fails (before config.yaml exists / before code exists)**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError` or missing file) if run before steps 1-6; after steps 1-6 it should already PASS.

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git init  # only if not already a repo
git add requirements.txt config/config.yaml .env.example .gitignore \
  indicators/__init__.py strategy/__init__.py risk/__init__.py backtest/__init__.py \
  utils/__init__.py utils/config.py kite/__init__.py tests/__init__.py tests/test_config.py
git commit -m "chore: project scaffolding and config loader"
```

---

### Task 2: Kite auth module + login script

**Files:**
- Create: `kite/auth.py`
- Create: `kite/login.py`

**Interfaces:**
- Consumes: `python-dotenv`, `kiteconnect.KiteConnect`
- Produces: `get_kite_client() -> KiteConnect` — used by `backtest/data_loader.py` (Task 3) and, later, by Phase 2's live execution module.

This is thin I/O glue around the SDK's own login flow — the SDK is mocked-out already, and there's no branching logic worth a unit test here (per the "trivial code needs no test" rule). It's validated end-to-end when `login.py` is actually run against Kite in Task 3's manual check.

- [ ] **Step 1: Write kite/auth.py**

```python
"""KiteConnect client construction from stored credentials/access token."""
import os
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()


def get_kite_client() -> KiteConnect:
    """Build an authenticated KiteConnect client using the access token
    written by kite/login.py. Raises if no token file exists yet."""
    api_key = os.environ["KITE_API_KEY"]
    token_path = Path(os.environ.get("KITE_ACCESS_TOKEN_FILE", "kite/.access_token"))
    if not token_path.exists():
        raise RuntimeError(
            f"No access token at {token_path}. Run `python -m kite.login` first."
        )
    access_token = token_path.read_text().strip()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite
```

- [ ] **Step 2: Write kite/login.py**

```python
"""One-off daily login: exchange a request_token for an access_token.

Kite Connect access tokens expire every day. Run this once per trading day:
    python -m kite.login
It prints a login URL, you log in in the browser, paste the redirected
request_token back here, and it saves the access token to disk.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()


def main() -> None:
    api_key = os.environ["KITE_API_KEY"]
    api_secret = os.environ["KITE_API_SECRET"]
    token_path = Path(os.environ.get("KITE_ACCESS_TOKEN_FILE", "kite/.access_token"))

    kite = KiteConnect(api_key=api_key)
    print("Login URL:", kite.login_url())
    request_token = input("Paste the request_token from the redirect URL: ").strip()

    session = kite.generate_session(request_token, api_secret=api_secret)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(session["access_token"])
    print(f"Access token saved to {token_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add kite/auth.py kite/login.py
git commit -m "feat: Kite Connect auth client and daily login script"
```

---

### Task 3: Historical data loader + 5-minute resample

**Files:**
- Create: `backtest/data_loader.py`
- Test: `tests/test_data_loader.py`

**Interfaces:**
- Consumes: `kite.auth.get_kite_client`
- Produces: `fetch_historical(kite, instrument_token: int, from_date: str, to_date: str, interval: str = "minute") -> pd.DataFrame` (columns: `open, high, low, close, volume`, `DatetimeIndex`), `resample_to_5min(df_1m: pd.DataFrame) -> pd.DataFrame` (same columns) — both used by `backtest/engine.py` (Task 14) and `backtest/run_backtest.py` (Task 16).

- [ ] **Step 1: Write the failing test (resample logic only — pure, no network)**

```python
# tests/test_data_loader.py
import pandas as pd

from backtest.data_loader import resample_to_5min


def _make_1m_df(n_minutes=10, start="2026-01-05 09:15:00"):
    idx = pd.date_range(start, periods=n_minutes, freq="1min")
    data = {
        "open": range(100, 100 + n_minutes),
        "high": [o + 1 for o in range(100, 100 + n_minutes)],
        "low": [o - 1 for o in range(100, 100 + n_minutes)],
        "close": [o + 0.5 for o in range(100, 100 + n_minutes)],
        "volume": [10] * n_minutes,
    }
    return pd.DataFrame(data, index=idx)


def test_resample_to_5min_aggregates_ohlcv_correctly():
    df_1m = _make_1m_df(10)
    df_5m = resample_to_5min(df_1m)

    assert len(df_5m) == 2
    first_bar = df_5m.iloc[0]
    assert first_bar["open"] == df_1m["open"].iloc[0]
    assert first_bar["high"] == df_1m["high"].iloc[0:5].max()
    assert first_bar["low"] == df_1m["low"].iloc[0:5].min()
    assert first_bar["close"] == df_1m["close"].iloc[4]
    assert first_bar["volume"] == df_1m["volume"].iloc[0:5].sum()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_data_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.data_loader'`

- [ ] **Step 3: Write backtest/data_loader.py**

```python
"""Historical candle fetch (Kite) and timeframe resampling."""
import pandas as pd
from kiteconnect import KiteConnect

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def fetch_historical(
    kite: KiteConnect,
    instrument_token: int,
    from_date: str,
    to_date: str,
    interval: str = "minute",
) -> pd.DataFrame:
    """Fetch OHLCV candles from Kite's historical data API.

    from_date/to_date: "YYYY-MM-DD" strings.
    """
    candles = kite.historical_data(instrument_token, from_date, to_date, interval)
    df = pd.DataFrame(candles)
    df = df.rename(columns={"date": "datetime"}).set_index("datetime")
    df.index = pd.to_datetime(df.index)
    return df[["open", "high", "low", "close", "volume"]]


def resample_to_5min(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute OHLCV candles into 5-minute candles."""
    df_5m = df_1m.resample("5min").agg(_AGG)
    return df_5m.dropna(subset=["open"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_data_loader.py -v`
Expected: PASS

- [ ] **Step 5: Manual check — real historical fetch (requires a live access token)**

```bash
python -m kite.login   # complete once, saves access token
python -c "
from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical
kite = get_kite_client()
instruments = kite.instruments('BSE')
sensex = next(i for i in instruments if i['tradingsymbol'] == 'SENSEX' and i['segment'] == 'INDICES')
df = fetch_historical(kite, sensex['instrument_token'], '2026-07-01', '2026-07-10', 'minute')
print(df.head())
print(len(df))
"
```
Expected: prints a non-empty DataFrame of 1-minute SENSEX candles.

- [ ] **Step 6: Commit**

```bash
git add backtest/data_loader.py tests/test_data_loader.py
git commit -m "feat: historical data fetch and 5-minute resampling"
```

---

### Task 4: EMA indicator + slope + cross signal

**Files:**
- Create: `indicators/ema.py`
- Test: `tests/test_ema.py`

**Interfaces:**
- Produces: `calculate_ema(series: pd.Series, length: int) -> pd.Series`, `ema_slope(ema_series: pd.Series, lookback: int) -> float`, `ema_cross_signal(fast: pd.Series, slow: pd.Series, slope_fast: float, slope_threshold: float) -> str | None` (`"bullish"`, `"bearish"`, or `None`) — used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ema.py
import pandas as pd

from indicators.ema import calculate_ema, ema_slope, ema_cross_signal


def test_calculate_ema_of_constant_series_equals_constant():
    series = pd.Series([50.0] * 30)
    ema = calculate_ema(series, length=9)
    assert abs(ema.iloc[-1] - 50.0) < 1e-9


def test_ema_slope_positive_on_rising_series():
    series = pd.Series(range(1, 21), dtype=float)
    ema = calculate_ema(series, length=3)
    slope = ema_slope(ema, lookback=3)
    assert slope > 0


def test_ema_cross_signal_detects_bullish_cross_with_sufficient_slope():
    fast = pd.Series([9, 9, 11])
    slow = pd.Series([10, 10, 10])
    assert ema_cross_signal(fast, slow, slope_fast=1.0, slope_threshold=0.05) == "bullish"


def test_ema_cross_signal_none_when_slope_too_small():
    fast = pd.Series([9, 9, 11])
    slow = pd.Series([10, 10, 10])
    assert ema_cross_signal(fast, slow, slope_fast=0.01, slope_threshold=0.05) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.ema'`

- [ ] **Step 3: Write indicators/ema.py**

```python
"""EMA calculation, slope, and crossover signal."""
import pandas as pd


def calculate_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def ema_slope(ema_series: pd.Series, lookback: int) -> float:
    """Simple average rate of change over `lookback` bars."""
    if len(ema_series) < lookback + 1:
        return 0.0
    return (ema_series.iloc[-1] - ema_series.iloc[-1 - lookback]) / lookback


def ema_cross_signal(
    fast: pd.Series, slow: pd.Series, slope_fast: float, slope_threshold: float
) -> str | None:
    """Bullish: fast crosses above slow AND fast slope >= threshold.
    Bearish: fast crosses below slow AND fast slope <= -threshold."""
    if len(fast) < 2 or len(slow) < 2:
        return None
    crossed_up = fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]
    crossed_down = fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]
    if crossed_up and slope_fast >= slope_threshold:
        return "bullish"
    if crossed_down and slope_fast <= -slope_threshold:
        return "bearish"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/ema.py tests/test_ema.py
git commit -m "feat: EMA indicator with slope and crossover signal"
```

---

### Task 5: RSI indicator

**Files:**
- Create: `indicators/rsi.py`
- Test: `tests/test_rsi.py`

**Interfaces:**
- Produces: `calculate_rsi(series: pd.Series, length: int) -> pd.Series`, `rsi_signal(rsi_series: pd.Series, midline: float) -> str | None` — used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rsi.py
import pandas as pd

from indicators.rsi import calculate_rsi, rsi_signal


def test_rsi_monotonic_rise_approaches_100():
    series = pd.Series(range(1, 41), dtype=float)
    rsi = calculate_rsi(series, length=14)
    assert rsi.iloc[-1] > 95


def test_rsi_monotonic_fall_approaches_0():
    series = pd.Series(range(40, 0, -1), dtype=float)
    rsi = calculate_rsi(series, length=14)
    assert rsi.iloc[-1] < 5


def test_rsi_signal_bullish_on_cross_above_midline_and_rising():
    rsi = pd.Series([48, 49, 52])
    assert rsi_signal(rsi, midline=50) == "bullish"


def test_rsi_signal_none_when_crossed_but_falling():
    rsi = pd.Series([48, 55, 52])  # crossed above earlier, now falling
    assert rsi_signal(rsi, midline=50) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rsi.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.rsi'`

- [ ] **Step 3: Write indicators/rsi.py**

```python
"""Wilder's RSI and midline-cross signal."""
import pandas as pd


def calculate_rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_signal(rsi_series: pd.Series, midline: float) -> str | None:
    """Bullish: crossed above midline AND still rising.
    Bearish: crossed below midline AND still falling.
    Overbought/oversold zones are intentionally NOT used to generate
    signals here — per spec they're confirmation-only, applied in strategy.py."""
    if len(rsi_series) < 2:
        return None
    crossed_above = rsi_series.iloc[-2] <= midline and rsi_series.iloc[-1] > midline
    crossed_below = rsi_series.iloc[-2] >= midline and rsi_series.iloc[-1] < midline
    rising = rsi_series.iloc[-1] > rsi_series.iloc[-2]
    falling = rsi_series.iloc[-1] < rsi_series.iloc[-2]
    if crossed_above and rising:
        return "bullish"
    if crossed_below and falling:
        return "bearish"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rsi.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/rsi.py tests/test_rsi.py
git commit -m "feat: RSI indicator with midline crossover signal"
```

---

### Task 6: ATR indicator + ATR-SMA volatility filter

**Files:**
- Create: `indicators/atr.py`
- Test: `tests/test_atr.py`

**Interfaces:**
- Produces: `true_range(df: pd.DataFrame) -> pd.Series`, `calculate_atr(df: pd.DataFrame, length: int) -> pd.Series`, `atr_filter_passes(df: pd.DataFrame, length: int, sma_length: int) -> bool` — `true_range` and `calculate_atr` are reused by `indicators/adx.py` (Task 7) and `indicators/supertrend.py` (Task 8); `atr_filter_passes` is used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_atr.py
import pandas as pd

from indicators.atr import true_range, calculate_atr, atr_filter_passes


def _flat_df(n=30, price=100.0):
    return pd.DataFrame(
        {
            "open": [price] * n,
            "high": [price] * n,
            "low": [price] * n,
            "close": [price] * n,
            "volume": [1000] * n,
        }
    )


def test_true_range_zero_for_flat_series():
    df = _flat_df()
    tr = true_range(df)
    assert (tr.fillna(0) == 0).all()


def test_atr_non_negative_on_volatile_series():
    df = _flat_df(30)
    df.loc[10:, "high"] += 5
    df.loc[10:, "low"] -= 5
    atr = calculate_atr(df, length=14)
    assert (atr.dropna() >= 0).all()
    assert atr.iloc[-1] > 0


def test_atr_filter_passes_true_when_recent_volatility_spikes():
    df = _flat_df(40)
    df.loc[35:, "high"] += 10
    df.loc[35:, "low"] -= 10
    assert atr_filter_passes(df, length=14, sma_length=14) is True


def test_atr_filter_passes_false_on_flat_series():
    df = _flat_df(40)
    assert atr_filter_passes(df, length=14, sma_length=14) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_atr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.atr'`

- [ ] **Step 3: Write indicators/atr.py**

```python
"""Wilder's True Range / ATR and the ATR-vs-ATR-SMA volatility filter."""
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def calculate_atr(df: pd.DataFrame, length: int) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def atr_filter_passes(df: pd.DataFrame, length: int, sma_length: int) -> bool:
    """True only when current volatility (ATR) exceeds its own moving
    average — rejects low-volatility, choppy conditions."""
    atr = calculate_atr(df, length)
    atr_sma = atr.rolling(sma_length).mean()
    if pd.isna(atr.iloc[-1]) or pd.isna(atr_sma.iloc[-1]):
        return False
    return atr.iloc[-1] > atr_sma.iloc[-1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_atr.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/atr.py tests/test_atr.py
git commit -m "feat: ATR indicator and volatility filter"
```

---

### Task 7: ADX indicator

**Files:**
- Create: `indicators/adx.py`
- Test: `tests/test_adx.py`

**Interfaces:**
- Consumes: `indicators.atr.true_range`
- Produces: `calculate_adx(df: pd.DataFrame, length: int) -> pd.Series`, `adx_filter_passes(df: pd.DataFrame, length: int, threshold: float) -> bool` — used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adx.py
import numpy as np
import pandas as pd

from indicators.adx import calculate_adx, adx_filter_passes


def _trending_df(n=60):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(np.linspace(100, 160, n))
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def _choppy_df(n=60):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(100 + np.sin(np.arange(n)) * 0.5)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_adx_in_valid_range():
    df = _trending_df()
    adx = calculate_adx(df, length=14)
    assert (adx.dropna() >= 0).all()
    assert (adx.dropna() <= 100).all()


def test_adx_higher_for_strong_trend_than_choppy_range():
    trending_adx = calculate_adx(_trending_df(), length=14).iloc[-1]
    choppy_adx = calculate_adx(_choppy_df(), length=14).iloc[-1]
    assert trending_adx > choppy_adx


def test_adx_filter_passes_true_for_strong_trend():
    assert adx_filter_passes(_trending_df(), length=14, threshold=25) is True


def test_adx_filter_passes_false_for_choppy_range():
    assert adx_filter_passes(_choppy_df(), length=14, threshold=25) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_adx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.adx'`

- [ ] **Step 3: Write indicators/adx.py**

```python
"""Wilder's ADX (trend strength) and its threshold filter."""
import numpy as np
import pandas as pd

from indicators.atr import true_range


def calculate_adx(df: pd.DataFrame, length: int) -> pd.Series:
    high, low = df["high"], df["low"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr = tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / length, min_periods=length, adjust=False
    ).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / length, min_periods=length, adjust=False
    ).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def adx_filter_passes(df: pd.DataFrame, length: int, threshold: float) -> bool:
    adx = calculate_adx(df, length)
    if pd.isna(adx.iloc[-1]):
        return False
    return adx.iloc[-1] > threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_adx.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/adx.py tests/test_adx.py
git commit -m "feat: ADX trend-strength indicator and threshold filter"
```

---

### Task 8: SuperTrend indicator (dual instance + agreement)

**Files:**
- Create: `indicators/supertrend.py`
- Test: `tests/test_supertrend.py`

**Interfaces:**
- Consumes: `indicators.atr.calculate_atr`
- Produces: `supertrend(df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame` (columns `supertrend`, `trend` where `trend` is `1`/`-1`), `supertrend_agree(trend_a: int, trend_b: int) -> str | None` (`"bullish"`/`"bearish"`/`None`) — used by `strategy/strategy.py` (Task 11) and `backtest/engine.py` (Task 14, for trailing-stop reversal exit).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_supertrend.py
import numpy as np
import pandas as pd

from indicators.supertrend import supertrend, supertrend_agree


def _uptrend_df(n=50):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(np.linspace(100, 150, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_supertrend_columns_present():
    df = _uptrend_df()
    result = supertrend(df, length=10, multiplier=3)
    assert "supertrend" in result.columns
    assert "trend" in result.columns
    assert set(result["trend"].dropna().unique()).issubset({1, -1})


def test_supertrend_trend_is_up_in_sustained_uptrend():
    df = _uptrend_df()
    result = supertrend(df, length=10, multiplier=3)
    assert result["trend"].iloc[-1] == 1
    assert result["supertrend"].iloc[-1] < df["close"].iloc[-1]


def test_supertrend_agree_bullish_when_both_up():
    assert supertrend_agree(1, 1) == "bullish"


def test_supertrend_agree_bearish_when_both_down():
    assert supertrend_agree(-1, -1) == "bearish"


def test_supertrend_agree_none_when_disagreeing():
    assert supertrend_agree(1, -1) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_supertrend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.supertrend'`

- [ ] **Step 3: Write indicators/supertrend.py**

```python
"""SuperTrend indicator (standard recursive-band algorithm) and the
two-instance agreement check used as the primary trend filter."""
import numpy as np
import pandas as pd

from indicators.atr import calculate_atr


def supertrend(df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    atr = calculate_atr(df, length)
    hl2 = (high + low) / 2

    upperband = hl2 + multiplier * atr
    lowerband = hl2 - multiplier * atr
    final_upper = upperband.copy()
    final_lower = lowerband.copy()

    # ponytail: O(n) iloc loop, not vectorized — SuperTrend's band is
    # recursive on its own previous value, which pandas can't express as a
    # vector op. Fine at backtest/live tick volumes; revisit only if this
    # profiles as a bottleneck on very large historical ranges.
    for i in range(1, len(df)):
        if close.iloc[i - 1] <= final_upper.iloc[i - 1]:
            final_upper.iloc[i] = min(upperband.iloc[i], final_upper.iloc[i - 1])
        else:
            final_upper.iloc[i] = upperband.iloc[i]

        if close.iloc[i - 1] >= final_lower.iloc[i - 1]:
            final_lower.iloc[i] = max(lowerband.iloc[i], final_lower.iloc[i - 1])
        else:
            final_lower.iloc[i] = lowerband.iloc[i]

    trend = pd.Series(index=df.index, dtype=int)
    trend.iloc[0] = 1
    for i in range(1, len(df)):
        if trend.iloc[i - 1] == 1 and close.iloc[i] < final_lower.iloc[i]:
            trend.iloc[i] = -1
        elif trend.iloc[i - 1] == -1 and close.iloc[i] > final_upper.iloc[i]:
            trend.iloc[i] = 1
        else:
            trend.iloc[i] = trend.iloc[i - 1]

    line = np.where(trend == 1, final_lower, final_upper)
    return pd.DataFrame({"supertrend": line, "trend": trend}, index=df.index)


def supertrend_agree(trend_a: int, trend_b: int) -> str | None:
    if trend_a == 1 and trend_b == 1:
        return "bullish"
    if trend_a == -1 and trend_b == -1:
        return "bearish"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_supertrend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/supertrend.py tests/test_supertrend.py
git commit -m "feat: SuperTrend indicator and dual-instance agreement check"
```

---

### Task 9: Volume confirmation

**Files:**
- Create: `indicators/volume.py`
- Test: `tests/test_volume.py`

**Interfaces:**
- Produces: `volume_confirms(df: pd.DataFrame, lookback: int, multiplier: float) -> bool` — used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_volume.py
import pandas as pd

from indicators.volume import volume_confirms


def _df_with_volumes(volumes):
    return pd.DataFrame({"volume": volumes})


def test_volume_confirms_true_on_breakout_spike():
    volumes = [100] * 20 + [200]  # last bar is 2x the prior 20-bar average
    df = _df_with_volumes(volumes)
    assert volume_confirms(df, lookback=20, multiplier=1.5) is True


def test_volume_confirms_false_on_average_volume():
    volumes = [100] * 20 + [110]
    df = _df_with_volumes(volumes)
    assert volume_confirms(df, lookback=20, multiplier=1.5) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_volume.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.volume'`

- [ ] **Step 3: Write indicators/volume.py**

```python
"""Breakout volume confirmation: current bar vs the trailing average."""
import pandas as pd


def volume_confirms(df: pd.DataFrame, lookback: int, multiplier: float) -> bool:
    """True when the latest bar's volume exceeds `multiplier`x the average
    of the preceding `lookback` bars (excluding the latest bar itself)."""
    if len(df) < lookback + 1:
        return False
    avg_volume = df["volume"].iloc[-lookback - 1 : -1].mean()
    return df["volume"].iloc[-1] > multiplier * avg_volume
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_volume.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/volume.py tests/test_volume.py
git commit -m "feat: volume confirmation filter"
```

---

### Task 10: VWAP indicator

**Files:**
- Create: `indicators/vwap.py`
- Test: `tests/test_vwap.py`

**Interfaces:**
- Produces: `calculate_vwap(df: pd.DataFrame) -> pd.Series` (session-anchored, resets daily), `price_above_vwap(df, vwap_series) -> bool`, `price_below_vwap(df, vwap_series) -> bool` — used by `strategy/strategy.py` (Task 11).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vwap.py
import pandas as pd

from indicators.vwap import calculate_vwap, price_above_vwap, price_below_vwap


def _two_day_df():
    idx = pd.date_range("2026-01-05 09:15", periods=4, freq="1min").append(
        pd.date_range("2026-01-06 09:15", periods=4, freq="1min")
    )
    return pd.DataFrame(
        {
            "high": [101, 102, 103, 104] * 2,
            "low": [99, 100, 101, 102] * 2,
            "close": [100, 101, 102, 103] * 2,
            "volume": [10, 20, 10, 20] * 2,
        },
        index=idx,
    )


def test_vwap_resets_each_session():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    # first bar of day 2 should equal that bar's own typical price,
    # not be dragged down by day 1's cumulative average
    day2_first_typical = (df["high"].iloc[4] + df["low"].iloc[4] + df["close"].iloc[4]) / 3
    assert abs(vwap.iloc[4] - day2_first_typical) < 1e-9


def test_vwap_within_session_high_low_range():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    assert (vwap >= df["low"]).all()
    assert (vwap <= df["high"]).all()


def test_price_above_and_below_vwap():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    assert price_above_vwap(df, vwap) == (df["close"].iloc[-1] > vwap.iloc[-1])
    assert price_below_vwap(df, vwap) == (df["close"].iloc[-1] < vwap.iloc[-1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vwap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'indicators.vwap'`

- [ ] **Step 3: Write indicators/vwap.py**

```python
"""Session-anchored VWAP (resets at the start of each trading day)."""
import pandas as pd


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    tp_vol = typical_price * df["volume"]
    cum_tp_vol = tp_vol.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    return cum_tp_vol / cum_vol


def price_above_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] > vwap_series.iloc[-1]


def price_below_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] < vwap_series.iloc[-1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vwap.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add indicators/vwap.py tests/test_vwap.py
git commit -m "feat: session-anchored VWAP indicator"
```

---

### Task 11: Strategy engine — combine all 7 indicators into entry signals

**Files:**
- Create: `strategy/strategy.py`
- Test: `tests/test_strategy.py`

**Interfaces:**
- Consumes: every function from Tasks 4-10 (`indicators.ema`, `indicators.rsi`, `indicators.atr`, `indicators.adx`, `indicators.supertrend`, `indicators.volume`, `indicators.vwap`)
- Produces: `Signal` dataclass (`direction: str | None`, `reasons: list[str]`), `generate_signal(df_1m: pd.DataFrame, df_5m: pd.DataFrame, cfg: dict) -> Signal` — used by `backtest/engine.py` (Task 14). `direction` is `"BUY_CALL"`, `"SELL_PUT"`, or `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strategy.py
import numpy as np
import pandas as pd

from strategy.strategy import generate_signal

CFG = {
    "indicators": {
        "supertrend_fast": {"length": 10, "multiplier": 1},
        "supertrend_slow": {"length": 10, "multiplier": 3},
        "ema_fast_length": 9,
        "ema_slow_length": 15,
        "ema_slope_lookback": 3,
        "ema_slope_threshold": 0.01,
        "rsi_length": 14,
        "rsi_midline": 50,
        "adx_length": 14,
        "adx_threshold": 25,
        "atr_length": 14,
        "atr_sma_length": 14,
        "volume_lookback": 20,
        "volume_multiplier": 1.5,
    }
}


def _bullish_df(n=80, freq="1min"):
    """A synthetic series engineered to satisfy every bullish condition:
    steady strong uptrend, a volume spike on the last bar, high enough
    range to keep ADX/ATR filters open."""
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq=freq)
    close = pd.Series(np.linspace(100, 100 + n * 0.8, n))
    high = close + 1.0
    low = close - 1.0
    volume = pd.Series([1000] * (n - 1) + [5000])
    return pd.DataFrame(
        {"open": close - 0.3, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _flat_df(n=80, freq="1min"):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq=freq)
    close = pd.Series([100.0] * n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": [1000] * n,
        },
        index=idx,
    )


def test_generate_signal_buy_call_when_all_bullish_conditions_align():
    df_1m = _bullish_df()
    df_5m = _bullish_df(n=80, freq="5min")
    signal = generate_signal(df_1m, df_5m, CFG)
    assert signal.direction == "BUY_CALL"
    assert len(signal.reasons) > 0


def test_generate_signal_none_in_flat_choppy_market():
    df_1m = _flat_df()
    df_5m = _flat_df(n=80, freq="5min")
    signal = generate_signal(df_1m, df_5m, CFG)
    assert signal.direction is None


def test_generate_signal_none_when_higher_timeframe_disagrees():
    df_1m = _bullish_df()
    # 5-minute series trending down while 1-minute trends up
    idx = pd.date_range("2026-01-05 09:15", periods=80, freq="5min")
    close = pd.Series(np.linspace(200, 200 - 80 * 0.8, 80))
    df_5m = pd.DataFrame(
        {
            "open": close + 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [1000] * 80,
        },
        index=idx,
    )
    signal = generate_signal(df_1m, df_5m, CFG)
    assert signal.direction is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'strategy.strategy'`

- [ ] **Step 3: Write strategy/strategy.py**

```python
"""Combine all 7 indicators into a single entry signal per the spec's
ALL-conditions-must-agree rule. Callers must pass DataFrames containing
only closed candles (the last row is the most recently closed bar)."""
from dataclasses import dataclass, field

import pandas as pd

from indicators.adx import adx_filter_passes
from indicators.atr import atr_filter_passes
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.rsi import calculate_rsi, rsi_signal
from indicators.supertrend import supertrend, supertrend_agree
from indicators.volume import volume_confirms
from indicators.vwap import calculate_vwap, price_above_vwap, price_below_vwap


@dataclass
class Signal:
    direction: str | None
    reasons: list[str] = field(default_factory=list)


def _higher_timeframe_trend(df_5m: pd.DataFrame, cfg: dict) -> str | None:
    st_cfg = cfg["indicators"]
    st1 = supertrend(df_5m, **st_cfg["supertrend_fast"])
    st2 = supertrend(df_5m, **st_cfg["supertrend_slow"])
    return supertrend_agree(st1["trend"].iloc[-1], st2["trend"].iloc[-1])


def generate_signal(df_1m: pd.DataFrame, df_5m: pd.DataFrame, cfg: dict) -> Signal:
    ind = cfg["indicators"]

    higher_trend = _higher_timeframe_trend(df_5m, cfg)
    if higher_trend is None:
        return Signal(direction=None, reasons=["higher timeframe trend undecided"])

    st1 = supertrend(df_1m, **ind["supertrend_fast"])
    st2 = supertrend(df_1m, **ind["supertrend_slow"])
    st_trend = supertrend_agree(st1["trend"].iloc[-1], st2["trend"].iloc[-1])
    if st_trend != higher_trend:
        return Signal(direction=None, reasons=["1-minute SuperTrend disagrees with higher timeframe"])

    ema_fast = calculate_ema(df_1m["close"], ind["ema_fast_length"])
    ema_slow = calculate_ema(df_1m["close"], ind["ema_slow_length"])
    slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
    ema_signal = ema_cross_signal(ema_fast, ema_slow, slope_fast, ind["ema_slope_threshold"])
    if ema_signal != st_trend:
        return Signal(direction=None, reasons=["no EMA crossover matching trend direction"])

    rsi = calculate_rsi(df_1m["close"], ind["rsi_length"])
    rsi_sig = rsi_signal(rsi, ind["rsi_midline"])
    if rsi_sig != st_trend:
        return Signal(direction=None, reasons=["RSI midline signal disagrees with trend"])

    if not adx_filter_passes(df_1m, ind["adx_length"], ind["adx_threshold"]):
        return Signal(direction=None, reasons=["ADX below trend-strength threshold"])

    if not atr_filter_passes(df_1m, ind["atr_length"], ind["atr_sma_length"]):
        return Signal(direction=None, reasons=["ATR below its own moving average (low volatility)"])

    if not volume_confirms(df_1m, ind["volume_lookback"], ind["volume_multiplier"]):
        return Signal(direction=None, reasons=["volume did not confirm breakout"])

    vwap = calculate_vwap(df_1m)
    if st_trend == "bullish" and not price_above_vwap(df_1m, vwap):
        return Signal(direction=None, reasons=["price not above VWAP"])
    if st_trend == "bearish" and not price_below_vwap(df_1m, vwap):
        return Signal(direction=None, reasons=["price not below VWAP"])

    direction = "BUY_CALL" if st_trend == "bullish" else "SELL_PUT"
    reasons = [
        f"higher timeframe trend: {higher_trend}",
        f"dual SuperTrend agrees: {st_trend}",
        f"EMA{ind['ema_fast_length']}/EMA{ind['ema_slow_length']} cross: {ema_signal} (slope={slope_fast:.4f})",
        f"RSI midline signal: {rsi_sig}",
        "ADX confirms trend strength",
        "ATR confirms sufficient volatility",
        "volume confirms breakout",
        f"price {'above' if st_trend == 'bullish' else 'below'} VWAP",
    ]
    return Signal(direction=direction, reasons=reasons)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add strategy/strategy.py tests/test_strategy.py
git commit -m "feat: strategy engine combining all indicator conditions"
```

---

### Task 12: Risk manager — position sizing, stop selection, target

**Files:**
- Create: `risk/risk_manager.py`
- Test: `tests/test_risk_manager.py`

**Interfaces:**
- Produces: `calculate_stop_loss(direction: str, prev_candle: pd.Series, atr_value: float, atr_multiplier: float, entry_price: float) -> float`, `calculate_position_size(capital: float, risk_pct: float, entry_price: float, stop_price: float, lot_size: int) -> int`, `calculate_target(direction: str, entry_price: float, stop_price: float, rr_ratio: float) -> float` — used by `backtest/engine.py` (Task 14) and, unchanged, by Phase 2's live execution.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_manager.py
import pandas as pd

from risk.risk_manager import calculate_stop_loss, calculate_position_size, calculate_target


def test_stop_loss_buy_uses_wider_of_prev_low_and_atr_stop():
    prev_candle = pd.Series({"low": 98.0, "high": 103.0})
    # ATR stop = 100 - 1.5*3 = 95.5, wider (lower) than prev_low 98 -> use ATR stop
    stop = calculate_stop_loss("BUY_CALL", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 95.5


def test_stop_loss_buy_uses_prev_low_when_tighter_atr_stop():
    prev_candle = pd.Series({"low": 90.0, "high": 103.0})
    # ATR stop = 100 - 1.5*3 = 95.5, prev_low 90 is wider -> use prev_low
    stop = calculate_stop_loss("BUY_CALL", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 90.0


def test_stop_loss_sell_uses_wider_of_prev_high_and_atr_stop():
    prev_candle = pd.Series({"low": 97.0, "high": 101.0})
    # ATR stop = 100 + 1.5*3 = 104.5, wider (higher) than prev_high 101 -> use ATR stop
    stop = calculate_stop_loss("SELL_PUT", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 104.5


def test_position_size_respects_risk_amount_and_lot_size():
    # capital 100000, risk 1% = 1000, stop distance 10, lot_size 20
    # raw qty = 100, already a multiple of lot_size 20 -> 100
    qty = calculate_position_size(100000, 1.0, entry_price=100.0, stop_price=90.0, lot_size=20)
    assert qty == 100


def test_position_size_rounds_down_to_whole_lots():
    # raw qty = 1000/12 = 83.3 -> lots = 4 (4*20=80), rounds down
    qty = calculate_position_size(100000, 1.0, entry_price=100.0, stop_price=88.0, lot_size=20)
    assert qty == 80


def test_target_buy_is_entry_plus_rr_times_risk():
    target = calculate_target("BUY_CALL", entry_price=100.0, stop_price=90.0, rr_ratio=2.0)
    assert target == 120.0


def test_target_sell_is_entry_minus_rr_times_risk():
    target = calculate_target("SELL_PUT", entry_price=100.0, stop_price=110.0, rr_ratio=2.0)
    assert target == 80.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'risk.risk_manager'`

- [ ] **Step 3: Write risk/risk_manager.py**

```python
"""Position sizing, stop-loss selection, and target calculation.

Shared by the backtester (Phase 1) and, unmodified, by live/paper order
execution (Phase 2) — this module never places orders itself.
"""
import pandas as pd


def calculate_stop_loss(
    direction: str,
    prev_candle: pd.Series,
    atr_value: float,
    atr_multiplier: float,
    entry_price: float,
) -> float:
    """Always take whichever stop is further from entry (more room before
    a premature stop-out) between the previous candle's extreme and an
    ATR-multiple stop. See plan Global Constraints for the "larger stop"
    interpretation."""
    if direction == "BUY_CALL":
        prev_stop = prev_candle["low"]
        atr_stop = entry_price - atr_multiplier * atr_value
        return min(prev_stop, atr_stop)
    prev_stop = prev_candle["high"]
    atr_stop = entry_price + atr_multiplier * atr_value
    return max(prev_stop, atr_stop)


def calculate_position_size(
    capital: float, risk_pct: float, entry_price: float, stop_price: float, lot_size: int
) -> int:
    """Quantity = risk amount / stop distance, rounded down to whole lots."""
    risk_amount = capital * (risk_pct / 100)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0
    raw_qty = risk_amount / stop_distance
    lots = int(raw_qty // lot_size)
    return max(lots, 0) * lot_size


def calculate_target(direction: str, entry_price: float, stop_price: float, rr_ratio: float) -> float:
    risk = abs(entry_price - stop_price)
    reward = risk * rr_ratio
    return entry_price + reward if direction == "BUY_CALL" else entry_price - reward
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_risk_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add risk/risk_manager.py tests/test_risk_manager.py
git commit -m "feat: risk manager for stop loss, position sizing, target"
```

---

### Task 13: Trailing stop tracker

**Files:**
- Modify: `risk/risk_manager.py` (append the tracker class)
- Modify: `tests/test_risk_manager.py` (append tests)

**Interfaces:**
- Consumes: nothing new
- Produces: `TrailingStopTracker` class with `__init__(direction, entry_price, initial_stop, breakeven_r, trail_start_r)` and `update(price: float, supertrend_fast_value: float) -> float` (returns the current stop price) — used by `backtest/engine.py` (Task 14).

- [ ] **Step 1: Write the failing test (append to tests/test_risk_manager.py)**

```python
# append to tests/test_risk_manager.py
from risk.risk_manager import TrailingStopTracker


def test_trailing_stop_moves_to_breakeven_at_1r():
    # entry 100, stop 90 -> 1R = 10. Price at 110 = 1R reached.
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    stop = tracker.update(price=110.0, supertrend_fast_value=95.0)
    assert stop == 100.0  # moved to cost, not yet trailing


def test_trailing_stop_trails_via_supertrend_after_1_5r():
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=110.0, supertrend_fast_value=95.0)  # 1R: breakeven
    stop = tracker.update(price=115.0, supertrend_fast_value=108.0)  # 1.5R: trail
    assert stop == 108.0


def test_trailing_stop_never_moves_backward_for_buy():
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=115.0, supertrend_fast_value=108.0)  # trailing active, stop=108
    stop = tracker.update(price=116.0, supertrend_fast_value=105.0)  # supertrend dipped
    assert stop == 108.0  # does not retreat


def test_trailing_stop_sell_put_direction():
    tracker = TrailingStopTracker("SELL_PUT", entry_price=100.0, initial_stop=110.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=90.0, supertrend_fast_value=95.0)  # 1R down: breakeven
    stop = tracker.update(price=85.0, supertrend_fast_value=92.0)  # 1.5R: trail
    assert stop == 92.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_risk_manager.py -v -k trailing`
Expected: FAIL with `ImportError: cannot import name 'TrailingStopTracker'`

- [ ] **Step 3: Append TrailingStopTracker to risk/risk_manager.py**

```python
class TrailingStopTracker:
    """At 1R profit, moves stop to breakeven. At 1.5R, switches to
    trailing the given SuperTrend(10,1) value, only ever tightening."""

    def __init__(
        self,
        direction: str,
        entry_price: float,
        initial_stop: float,
        breakeven_r: float,
        trail_start_r: float,
    ):
        self.direction = direction
        self.entry_price = entry_price
        self.current_stop = initial_stop
        self.r_distance = abs(entry_price - initial_stop)
        self.breakeven_r = breakeven_r
        self.trail_start_r = trail_start_r
        self.breakeven_triggered = False
        self.trailing_active = False

    def _current_r(self, price: float) -> float:
        if self.r_distance == 0:
            return 0.0
        move = (price - self.entry_price) if self.direction == "BUY_CALL" else (self.entry_price - price)
        return move / self.r_distance

    def update(self, price: float, supertrend_fast_value: float) -> float:
        r = self._current_r(price)
        if r >= self.trail_start_r:
            self.trailing_active = True
        if self.trailing_active:
            if self.direction == "BUY_CALL":
                self.current_stop = max(self.current_stop, supertrend_fast_value)
            else:
                self.current_stop = min(self.current_stop, supertrend_fast_value)
        elif r >= self.breakeven_r and not self.breakeven_triggered:
            self.current_stop = self.entry_price
            self.breakeven_triggered = True
        return self.current_stop
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_risk_manager.py -v`
Expected: PASS (all tests, including the earlier stop/size/target ones)

- [ ] **Step 5: Commit**

```bash
git add risk/risk_manager.py tests/test_risk_manager.py
git commit -m "feat: trailing stop tracker (breakeven at 1R, SuperTrend trail at 1.5R)"
```

---

### Task 14: Backtest engine — walk-forward trade simulation

**Files:**
- Create: `backtest/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Consumes: `backtest.data_loader.resample_to_5min`, `strategy.strategy.generate_signal`, `indicators.atr.calculate_atr`, `indicators.supertrend.supertrend`, `risk.risk_manager.{calculate_stop_loss, calculate_position_size, calculate_target, TrailingStopTracker}`
- Produces: `Trade` dataclass (`entry_time, direction, entry_price, quantity, stop_price, target_price, exit_time, exit_price, exit_reason, entry_reasons`, and a `pnl` property), `BacktestEngine(df_1m: pd.DataFrame, cfg: dict)` with `.run() -> list[Trade]` — used by `backtest/run_backtest.py` (Task 16) and `backtest/metrics.py` (Task 15).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_engine.py
import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine

CFG = {
    "instrument": {"lot_size": 20},
    "indicators": {
        "supertrend_fast": {"length": 10, "multiplier": 1},
        "supertrend_slow": {"length": 10, "multiplier": 3},
        "ema_fast_length": 9,
        "ema_slow_length": 15,
        "ema_slope_lookback": 3,
        "ema_slope_threshold": 0.01,
        "rsi_length": 14,
        "rsi_midline": 50,
        "adx_length": 14,
        "adx_threshold": 25,
        "atr_length": 14,
        "atr_sma_length": 14,
        "volume_lookback": 20,
        "volume_multiplier": 1.5,
    },
    "risk": {
        "risk_pct": 1.0,
        "reward_risk_ratio": 2.0,
        "atr_stop_multiplier": 1.5,
        "breakeven_r": 1.0,
        "trail_start_r": 1.5,
        "max_trades_per_day": 5,
        "max_consecutive_losses": 3,
        "max_daily_loss_pct": 2.0,
    },
    "trading_hours": {"windows": [["09:15", "15:30"]], "square_off_time": "15:20"},
    "backtest": {"initial_capital": 100000, "warmup_bars": 60},
}


def _trending_day_df(n=200):
    """One trading day, strong sustained uptrend with a volume spike
    partway through, engineered to trigger a BUY_CALL entry and then run
    far enough to hit the profit target."""
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(np.linspace(100, 100 + n * 1.0, n))
    high = close + 1.0
    low = close - 1.0
    volume = pd.Series([1000] * n)
    volume.iloc[70:] = 5000
    return pd.DataFrame(
        {"open": close - 0.3, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_engine_produces_at_least_one_trade_on_strong_trend_day():
    df = _trending_day_df()
    engine = BacktestEngine(df, CFG)
    trades = engine.run()
    assert len(trades) >= 1
    assert trades[0].direction == "BUY_CALL"
    assert trades[0].exit_reason in {"target_hit", "supertrend_reversal", "ema_reversal", "eod_square_off", "backtest_end"}


def test_engine_closes_any_open_trade_by_end_of_data():
    df = _trending_day_df()
    engine = BacktestEngine(df, CFG)
    trades = engine.run()
    for t in trades:
        assert t.exit_time is not None
        assert t.exit_price is not None


def test_engine_never_opens_a_second_trade_while_one_is_open():
    df = _trending_day_df()
    engine = BacktestEngine(df, CFG)
    trades = engine.run()
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time


def test_engine_respects_max_trades_per_day():
    df = _trending_day_df(n=390)  # full trading day of 1-min bars
    cfg = {**CFG, "risk": {**CFG["risk"], "max_trades_per_day": 1}}
    engine = BacktestEngine(df, cfg)
    trades = engine.run()
    same_day = [t for t in trades if t.entry_time.date() == df.index[0].date()]
    assert len(same_day) <= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.engine'`

- [ ] **Step 3: Write backtest/engine.py**

```python
"""Walk-forward backtest simulation. Iterates 1-minute bars in order,
never looking ahead, generating signals only from closed candles and
managing at most one open position at a time."""
from dataclasses import dataclass, field
from datetime import time as dt_time

import pandas as pd

from backtest.data_loader import resample_to_5min
from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend
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
    entry_reasons: list[str] = field(default_factory=list)
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float | None:
        if self.exit_price is None:
            return None
        mult = 1 if self.direction == "BUY_CALL" else -1
        return (self.exit_price - self.entry_price) * mult * self.quantity


class BacktestEngine:
    def __init__(self, df_1m: pd.DataFrame, cfg: dict):
        self.df_1m = df_1m
        self.df_5m = resample_to_5min(df_1m)
        self.cfg = cfg
        self.capital = cfg["backtest"]["initial_capital"]
        self.trades: list[Trade] = []
        self.open_trade: Trade | None = None
        self.tracker: TrailingStopTracker | None = None

        self.current_day = None
        self.trades_today = 0
        self.day_start_capital = self.capital
        self.consecutive_losses = 0
        self.trading_halted_today = False

    def run(self) -> list[Trade]:
        warmup = self.cfg["backtest"]["warmup_bars"]
        for i in range(warmup, len(self.df_1m)):
            window_1m = self.df_1m.iloc[: i + 1]
            now = window_1m.index[-1]
            self._roll_day(now)

            if self.open_trade is not None:
                self._manage_open_trade(window_1m)
                continue

            if self.trading_halted_today or self.trades_today >= self.cfg["risk"]["max_trades_per_day"]:
                continue
            if not self._within_trading_hours(now):
                continue

            window_5m = self.df_5m[self.df_5m.index <= now]
            if len(window_5m) < warmup:
                continue

            signal = generate_signal(window_1m, window_5m, self.cfg)
            if signal.direction:
                self._enter_trade(window_1m, signal)

        if self.open_trade is not None:
            self._close_trade(self.df_1m.index[-1], self.df_1m["close"].iloc[-1], "backtest_end")

        return self.trades

    def _roll_day(self, now: pd.Timestamp) -> None:
        day = now.date()
        if self.current_day != day:
            self.current_day = day
            self.trades_today = 0
            self.day_start_capital = self.capital
            self.consecutive_losses = 0
            self.trading_halted_today = False

    def _within_trading_hours(self, now: pd.Timestamp) -> bool:
        t = now.time()
        for start_s, end_s in self.cfg["trading_hours"]["windows"]:
            if dt_time.fromisoformat(start_s) <= t <= dt_time.fromisoformat(end_s):
                return True
        return False

    def _enter_trade(self, window_1m: pd.DataFrame, signal) -> None:
        entry_price = window_1m["close"].iloc[-1]
        prev_candle = window_1m.iloc[-2]
        atr_value = calculate_atr(window_1m, self.cfg["indicators"]["atr_length"]).iloc[-1]
        stop_price = calculate_stop_loss(
            signal.direction, prev_candle, atr_value, self.cfg["risk"]["atr_stop_multiplier"], entry_price
        )
        qty = calculate_position_size(
            self.capital, self.cfg["risk"]["risk_pct"], entry_price, stop_price, self.cfg["instrument"]["lot_size"]
        )
        if qty <= 0:
            return
        target_price = calculate_target(signal.direction, entry_price, stop_price, self.cfg["risk"]["reward_risk_ratio"])

        self.open_trade = Trade(
            entry_time=window_1m.index[-1],
            direction=signal.direction,
            entry_price=entry_price,
            quantity=qty,
            stop_price=stop_price,
            target_price=target_price,
            entry_reasons=signal.reasons,
        )
        self.tracker = TrailingStopTracker(
            signal.direction, entry_price, stop_price, self.cfg["risk"]["breakeven_r"], self.cfg["risk"]["trail_start_r"]
        )
        self.trades_today += 1

    def _manage_open_trade(self, window_1m: pd.DataFrame) -> None:
        now = window_1m.index[-1]
        price = window_1m["close"].iloc[-1]
        direction = self.open_trade.direction

        st_fast = supertrend(window_1m, **self.cfg["indicators"]["supertrend_fast"])
        st_value = st_fast["supertrend"].iloc[-1]
        st_trend = st_fast["trend"].iloc[-1]

        self.open_trade.stop_price = self.tracker.update(price, st_value)

        ind = self.cfg["indicators"]
        ema_fast = calculate_ema(window_1m["close"], ind["ema_fast_length"])
        ema_slow = calculate_ema(window_1m["close"], ind["ema_slow_length"])
        slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
        ema_signal = ema_cross_signal(ema_fast, ema_slow, slope_fast, ind["ema_slope_threshold"])
        ema_reversed = (direction == "BUY_CALL" and ema_signal == "bearish") or (
            direction == "SELL_PUT" and ema_signal == "bullish"
        )

        hit_target = price >= self.open_trade.target_price if direction == "BUY_CALL" else price <= self.open_trade.target_price
        hit_stop = price <= self.open_trade.stop_price if direction == "BUY_CALL" else price >= self.open_trade.stop_price
        st_reversed = (direction == "BUY_CALL" and st_trend == -1) or (direction == "SELL_PUT" and st_trend == 1)
        eod = now.time() >= dt_time.fromisoformat(self.cfg["trading_hours"]["square_off_time"])

        if hit_target:
            self._close_trade(now, self.open_trade.target_price, "target_hit")
        elif hit_stop:
            self._close_trade(now, self.open_trade.stop_price, "stop_hit")
        elif st_reversed:
            self._close_trade(now, price, "supertrend_reversal")
        elif ema_reversed:
            self._close_trade(now, price, "ema_reversal")
        elif eod:
            self._close_trade(now, price, "eod_square_off")

    def _close_trade(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        self.open_trade.exit_time = exit_time
        self.open_trade.exit_price = exit_price
        self.open_trade.exit_reason = reason
        self.trades.append(self.open_trade)

        pnl = self.open_trade.pnl
        self.capital += pnl
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

        daily_loss_pct = (self.day_start_capital - self.capital) / self.day_start_capital * 100
        if self.consecutive_losses >= self.cfg["risk"]["max_consecutive_losses"]:
            self.trading_halted_today = True
        if daily_loss_pct >= self.cfg["risk"]["max_daily_loss_pct"]:
            self.trading_halted_today = True

        self.open_trade = None
        self.tracker = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backtest/engine.py tests/test_engine.py
git commit -m "feat: backtest engine with walk-forward trade simulation"
```

---

### Task 15: Backtest performance metrics

**Files:**
- Create: `backtest/metrics.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `backtest.engine.Trade`
- Produces: `compute_metrics(trades: list[Trade]) -> dict` with keys `win_rate, profit_factor, max_drawdown, sharpe_ratio, average_trade, expectancy, equity_curve, monthly_returns, max_consecutive_wins, max_consecutive_losses` — used by `backtest/run_backtest.py` (Task 16).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py
import pandas as pd

from backtest.engine import Trade
from backtest.metrics import compute_metrics


def _trade(entry_time, exit_time, direction, entry_price, exit_price, qty=20):
    return Trade(
        entry_time=pd.Timestamp(entry_time),
        direction=direction,
        entry_price=entry_price,
        quantity=qty,
        stop_price=entry_price - 10 if direction == "BUY_CALL" else entry_price + 10,
        target_price=entry_price + 20 if direction == "BUY_CALL" else entry_price - 20,
        exit_time=pd.Timestamp(exit_time),
        exit_price=exit_price,
        exit_reason="target_hit",
    )


def test_compute_metrics_win_rate_and_profit_factor():
    trades = [
        _trade("2026-01-05 10:00", "2026-01-05 10:30", "BUY_CALL", 100, 120),  # +400
        _trade("2026-01-05 11:00", "2026-01-05 11:20", "BUY_CALL", 100, 90),  # -200
        _trade("2026-01-06 10:00", "2026-01-06 10:30", "BUY_CALL", 100, 130),  # +600
    ]
    m = compute_metrics(trades)
    assert m["win_rate"] == pytest_approx(2 / 3)
    assert m["profit_factor"] == pytest_approx(1000 / 200)
    assert len(m["equity_curve"]) == 3
    assert m["max_consecutive_wins"] == 1
    assert m["max_consecutive_losses"] == 1


def pytest_approx(x, tol=1e-6):
    import pytest

    return pytest.approx(x, abs=tol)


def test_compute_metrics_handles_no_trades_gracefully():
    m = compute_metrics([])
    assert m["win_rate"] == 0
    assert m["profit_factor"] == 0
    assert m["equity_curve"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.metrics'`

- [ ] **Step 3: Write backtest/metrics.py**

```python
"""Standard backtest performance statistics computed from a closed-trade list."""
import numpy as np
import pandas as pd

from backtest.engine import Trade


def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "win_rate": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "average_trade": 0,
            "expectancy": 0,
            "equity_curve": [],
            "monthly_returns": {},
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
        }

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    equity_curve = list(np.cumsum(pnls))
    running_max = np.maximum.accumulate(equity_curve)
    drawdowns = running_max - np.array(equity_curve)
    max_drawdown = float(drawdowns.max()) if len(drawdowns) else 0

    returns = pd.Series(pnls)
    sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(len(returns))) if returns.std() > 0 else 0

    average_trade = float(np.mean(pnls))
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    months = pd.Series(pnls, index=[t.exit_time for t in trades])
    monthly_returns = months.groupby(months.index.to_period("M")).sum().to_dict()
    monthly_returns = {str(k): float(v) for k, v in monthly_returns.items()}

    max_consecutive_wins = _max_consecutive(pnls, lambda p: p > 0)
    max_consecutive_losses = _max_consecutive(pnls, lambda p: p <= 0)

    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "average_trade": average_trade,
        "expectancy": expectancy,
        "equity_curve": equity_curve,
        "monthly_returns": monthly_returns,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
    }


def _max_consecutive(pnls: list[float], predicate) -> int:
    best = current = 0
    for p in pnls:
        if predicate(p):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backtest/metrics.py tests/test_metrics.py
git commit -m "feat: backtest performance metrics"
```

---

### Task 16: CLI runner + README

**Files:**
- Create: `backtest/run_backtest.py`
- Create: `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1-15
- Produces: a runnable CLI: `python -m backtest.run_backtest --from 2026-06-01 --to 2026-07-01`

- [ ] **Step 1: Write backtest/run_backtest.py**

```python
"""CLI entry point: fetch SENSEX historical data and run the backtest.

    python -m backtest.run_backtest --from 2026-06-01 --to 2026-07-01
"""
import argparse
import json

from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics
from utils.config import load_config


def _resolve_sensex_token(kite) -> int:
    cfg = load_config()["instrument"]
    instruments = kite.instruments(cfg["exchange"])
    match = next(
        i for i in instruments
        if i["tradingsymbol"] == cfg["index_symbol"] and i["segment"] == "INDICES"
    )
    return match["instrument_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the SENSEX signal engine")
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    kite = get_kite_client()
    token = _resolve_sensex_token(kite)

    df_1m = fetch_historical(kite, token, args.from_date, args.to_date, interval="minute")
    print(f"Fetched {len(df_1m)} 1-minute candles from {args.from_date} to {args.to_date}")

    engine = BacktestEngine(df_1m, cfg)
    trades = engine.run()
    metrics = compute_metrics(trades)

    print(f"\nTrades: {len(trades)}")
    print(json.dumps({k: v for k, v in metrics.items() if k not in ("equity_curve", "monthly_returns")}, indent=2))
    print("Monthly returns:", json.dumps(metrics["monthly_returns"], indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write README.md**

```markdown
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
```

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: all tests across Tasks 1-15 PASS

- [ ] **Step 4: Commit**

```bash
git add backtest/run_backtest.py README.md
git commit -m "feat: backtest CLI runner and Phase 1 README"
```

---

## Self-Review Notes

- **Spec coverage:** all 7 indicators (Tasks 4-10), entry conditions for both directions (Task 11), stop-loss/position-size/target (Task 12), trailing stop (Task 13), and all listed exit conditions — target hit, stop/trailing-stop hit, SuperTrend reversal, EMA opposite-direction cross, and 3:20 PM square-off — are wired into `BacktestEngine._manage_open_trade` (Task 14).
- Daily risk halts (max 5 trades/day, 3 consecutive losses, 2% daily loss) are implemented in the backtest engine (Task 14) so backtest results already reflect them; Phase 2 must reuse the same thresholds from `config.yaml`, not reimplement.
- Database logging, Telegram, dashboard, and live order execution are explicitly out of scope — separate plans, per the phased approach agreed with the user.
