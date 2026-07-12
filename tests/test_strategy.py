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
    """A synthetic series engineered to satisfy every bullish condition at
    the final (most recently closed) bar: a quiet, mildly choppy
    consolidation followed by a single breakout bar that carries a volume
    spike and enough range/momentum to flip EMA, RSI, ADX and ATR all at
    once. NB: a *steadily* trending ramp does not work here — EMA and RSI
    crossovers are single-bar trigger events, so they'd fire near the start
    of a steady ramp and never again, missing the final bar these tests
    inspect. The breakout has to land on the last bar instead.
    """
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq=freq)
    base = np.zeros(n)
    for i in range(1, n - 1):
        base[i] = base[i - 1] + (0.2 if i % 3 == 0 else -0.2)
    close = 100 + base
    close[-1] = close[-2] + 10.0
    high = close + 1.0
    low = close - 1.0
    volume = np.array([1000] * (n - 1) + [5000])
    return pd.DataFrame(
        {"open": close - 0.3, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _flat_df(n=80, freq="1min"):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq=freq)
    close = np.array([100.0] * n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": np.array([1000] * n),
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
    close = 200 - np.arange(80) * 0.8
    df_5m = pd.DataFrame(
        {
            "open": close + 0.3,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.array([1000] * 80),
        },
        index=idx,
    )
    signal = generate_signal(df_1m, df_5m, CFG)
    assert signal.direction is None
