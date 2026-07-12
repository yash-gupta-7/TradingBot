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


def test_rsi_signal_bearish_on_cross_below_midline_and_falling():
    rsi = pd.Series([52, 51, 48])  # crossed below midline, falling
    assert rsi_signal(rsi, midline=50) == "bearish"
