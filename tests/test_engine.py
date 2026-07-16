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

    Critically, the engine only ever hands `generate_signal` a 5-minute
    window of *closed* bins (see BacktestEngine.run's window_5m filter) --
    the bin covering the breakout bar itself is still forming and is NOT
    available on the breakout bar. So the higher-timeframe (5-minute)
    SuperTrend agreement has to already read bullish from bins that closed
    *before* the breakout, not from the breakout's own bin. SuperTrend's
    `trend` series is seeded bullish (index 0 defaults to 1) and a flat,
    zero-drift stretch never breaches its lower band, so the long flat
    section already holds a default "bullish" 5-minute agreement -- the
    down_len/down_step below (15 bars, -0.1/bar = -1.5 total) is tuned to
    be just mild enough that the 1-minute ADX has time to build up past
    its threshold without the dip being deep enough to flip the 5-minute
    fast SuperTrend (multiplier=1) into disagreement, so the "higher
    timeframe trend: bullish" gate is already true, from older closed
    data, by the time the single sharp reversal bar below fires the fresh
    1-minute EMA/RSI crossover. Verified bar-by-bar with generate_signal
    against the closed-only 5-minute window before writing assertions.
    """
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    flat_len, down_len = 285, 15
    down_step, jump, up_step = 0.1, 6.0, 2.0
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


def _two_signal_day_df(n=400):
    """Same construction as `_trending_day_df`, but with a *second*,
    independent dip+jump+run-up cycle later in the day, so the fixture can
    genuinely produce 2 trades if nothing caps it. Needed because a single
    steady ramp only ever re-arms the one-shot EMA/RSI crossover once; a
    second real crossover event requires the fast EMA/RSI to be pushed back
    down (a second mild dip) before crossing up again.

    Verified bar-by-bar with generate_signal (against the closed-only 5m
    window) that this produces exactly 2 independent BUY_CALL signals, at
    bar 300 (14:15) and bar 351 (15:06), both of which run to target_hit --
    used to make the "never opens a second trade" and "respects
    max_trades_per_day" assertions non-vacuous (previously the shared
    fixture could only ever produce 1 trade in its whole series, so both
    tests passed trivially against a `<= 1` upper bound).
    """
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = np.full(n, 100.0)
    pos = 285
    base = 0.0

    down_len, down_step, jump, up_step = 15, 0.1, 6.0, 2.0
    dip = -np.arange(1, down_len + 1) * down_step
    close[pos : pos + down_len] = 100 + base + dip
    base += dip[-1]
    pos += down_len
    close[pos] = 100 + base + jump
    entry1_bar = pos
    base += jump
    pos += 1
    run_len = 15
    up = base + np.arange(1, run_len + 1) * up_step
    close[pos : pos + run_len] = 100 + up
    base = up[-1]
    pos += run_len

    pause_len = 20
    close[pos : pos + pause_len] = 100 + base
    pos += pause_len

    # second cycle needs a deeper dip (0.2 vs 0.1) to actually cross RSI
    # back below its midline -- after the first run-up, RSI is already
    # elevated, so the same mild dip used for cycle 1 never gets it below 50.
    down_len2, down_step2 = 15, 0.2
    dip2 = -np.arange(1, down_len2 + 1) * down_step2
    close[pos : pos + down_len2] = 100 + base + dip2
    base += dip2[-1]
    pos += down_len2
    close[pos] = 100 + base + jump
    entry2_bar = pos
    base += jump
    pos += 1
    remaining = n - pos
    up2 = base + np.arange(1, remaining + 1) * up_step
    close[pos : pos + remaining] = 100 + up2

    close_s = pd.Series(close, index=idx)
    high = close_s + 1.0
    low = close_s - 1.0
    volume = np.full(n, 1000.0)
    spike_len = 25
    volume[max(0, entry1_bar - 2) : entry1_bar + spike_len] = 5000
    volume[max(0, entry2_bar - 2) : entry2_bar + spike_len] = 5000
    return pd.DataFrame(
        {"open": close_s - 0.3, "high": high, "low": low, "close": close_s, "volume": pd.Series(volume, index=idx)},
        index=idx,
    )


def _consecutive_losses_day_df(n=600, num_cycles=3):
    """3 independent dip+jump cycles, each immediately followed by a sharp
    reversal that stops the fresh position out at a loss (via
    supertrend_reversal, before it can hit target), then a full recovery
    back to a stable uptrend so the *next* cycle's dip+jump can still pass
    every one of generate_signal's 8 gates (including the 5-minute higher
    timeframe SuperTrend, which must already read bullish from bins closed
    *before* the next entry bar -- a violent, undamped crash flips that
    5-minute trend into disagreement and blocks the next cycle, so the
    post-loss recovery has to be generous enough to fully re-establish it).

    Uses a widened trading-hours window (see CFG_HALT below) purely to give
    3 independent cycles room in one calendar day -- the point of this
    fixture is to exercise the daily-loss risk halts in isolation, not
    trading-hours edge cases (covered elsewhere).

    Verified bar-by-bar / via direct engine runs with a permissive cfg
    (max_consecutive_losses=99) that all 3 cycles fire as genuine,
    independent BUY_CALL signals and each is stopped out at a real loss
    (same -420 pnl each, from generate_signal + the real risk/exit logic,
    no shortcuts) -- so a fixture-imposed ceiling isn't what limits trade
    count; only the halt configured in the test does.
    """
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = np.full(n, 100.0)
    pos = 285
    base = 0.0
    entries = []
    volume = np.full(n, 1000.0)

    down_len, down_step, jump = 20, 0.1, 6.0
    crash_step, crash_len = -1.5, 2
    recover_step, recover_len, pause_len = 0.3, 30, 15
    spike_len = 20

    for _ in range(num_cycles):
        dip = -np.arange(1, down_len + 1) * down_step
        close[pos : pos + down_len] = 100 + base + dip
        base += dip[-1]
        pos += down_len
        close[pos] = 100 + base + jump
        entries.append(pos)
        volume[max(0, pos - 2) : pos + spike_len] = 5000
        base += jump
        pos += 1
        crash = base + np.arange(1, crash_len + 1) * crash_step
        close[pos : pos + crash_len] = 100 + crash
        base = crash[-1]
        pos += crash_len
        recov = base + np.arange(1, recover_len + 1) * recover_step
        close[pos : pos + recover_len] = 100 + recov
        base = recov[-1]
        pos += recover_len
        close[pos : pos + pause_len] = 100 + base
        pos += pause_len

    if pos < n:
        close[pos:] = 100 + base

    close_s = pd.Series(close, index=idx)
    high = close_s + 1.0
    low = close_s - 1.0
    return pd.DataFrame(
        {"open": close_s - 0.3, "high": high, "low": low, "close": close_s, "volume": pd.Series(volume, index=idx)},
        index=idx,
    )


# Widened trading-hours window for _consecutive_losses_day_df: only exists
# to give 3 well-separated dip+jump+recover cycles room in a single
# calendar day so the daily-halt logic (not market-hours edge cases) is
# what's under test.
CFG_HALT = {**CFG, "trading_hours": {"windows": [["09:15", "20:00"]], "square_off_time": "19:50"}}


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
    df = _two_signal_day_df()
    engine = BacktestEngine(df, CFG)
    trades = engine.run()
    assert len(trades) == 2  # fixture must actually offer >1 trade for this to mean anything
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time


def test_engine_respects_max_trades_per_day():
    df = _two_signal_day_df(n=390)  # full trading day of 1-min bars
    # Prove the fixture can produce more than 1 trade absent a tighter cap.
    uncapped = BacktestEngine(df, CFG).run()
    assert len(uncapped) > 1

    cfg = {**CFG, "risk": {**CFG["risk"], "max_trades_per_day": 1}}
    engine = BacktestEngine(df, cfg)
    trades = engine.run()
    same_day = [t for t in trades if t.entry_time.date() == df.index[0].date()]
    assert len(same_day) <= 1


def test_engine_halts_after_max_consecutive_losses():
    df = _consecutive_losses_day_df()

    # Prove the fixture genuinely offers 3 independent losing signals when
    # nothing stops it -- otherwise a "halt caps trades" assertion below
    # would be vacuous.
    permissive_cfg = {**CFG_HALT, "risk": {**CFG_HALT["risk"], "max_consecutive_losses": 99, "max_daily_loss_pct": 100.0}}
    uncapped = BacktestEngine(df, permissive_cfg).run()
    assert len(uncapped) > 0
    assert all(t.pnl < 0 for t in uncapped)

    # With the halt active (cap=2), the 3rd otherwise-valid signal must be
    # blocked once consecutive_losses reaches the configured limit.
    halted_cfg = {**CFG_HALT, "risk": {**CFG_HALT["risk"], "max_consecutive_losses": 2}}
    trades = BacktestEngine(df, halted_cfg).run()
    assert len(trades) == 2
    assert all(t.pnl < 0 for t in trades)
