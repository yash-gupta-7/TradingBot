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


def _trending_day_df(n=400):
    """One trading day, engineered to trigger a BUY_CALL entry and then run
    far enough to hit the profit target.

    generate_signal requires the higher (5-minute) timeframe SuperTrend
    pair to have at least `warmup_bars` (60) closed 5-minute candles, which
    needs >= 300 one-minute bars of history -- and EMA-cross / RSI-cross
    are single-bar trigger events, so a *steadily* trending ramp from the
    very first bar would cross once near the start and never again, long
    before the 5-minute warmup is satisfied (see tests/test_strategy.py's
    `_bullish_df` for the same one-shot-crossover constraint at smaller
    scale). So the shape here is: a long quiet flat stretch (build the
    5-minute warmup) -> a mild, short downtrend (builds ADX trend-strength
    without moving price far from the session VWAP) -> a single sharp
    reversal bar (flips EMA9/15, RSI midline, and SuperTrend to bullish,
    with a matching volume spike, all on the same closed bar) -> a
    sustained run-up so the resulting position has room to hit its target
    before the day's square-off time.
    """
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    flat_len, down_len = 285, 20
    down_step, jump, up_step = 0.15, 6.0, 2.0
    breakout = flat_len + down_len
    flat = np.zeros(flat_len)
    down = -np.arange(1, down_len + 1) * down_step
    up_len = n - breakout
    up = down[-1] + jump + np.arange(up_len) * up_step
    base = np.concatenate([flat, down, up])
    close = pd.Series(100 + base, index=idx)
    high = close + 1.0
    low = close - 1.0
    volume = pd.Series([1000] * n, index=idx)
    volume.iloc[breakout:] = 5000
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
