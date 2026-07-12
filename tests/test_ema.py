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


def test_ema_cross_signal_detects_bearish_cross_with_sufficient_slope():
    fast = pd.Series([11, 11, 9])
    slow = pd.Series([10, 10, 10])
    assert ema_cross_signal(fast, slow, slope_fast=-1.0, slope_threshold=0.05) == "bearish"


def test_ema_cross_signal_none_when_bearish_slope_too_small():
    fast = pd.Series([11, 11, 9])
    slow = pd.Series([10, 10, 10])
    assert ema_cross_signal(fast, slow, slope_fast=-0.01, slope_threshold=0.05) is None


def test_ema_slope_returns_zero_for_short_series():
    series = pd.Series([1.0, 2.0])
    ema = calculate_ema(series, length=3)
    slope = ema_slope(ema, lookback=3)
    assert slope == 0.0


def test_ema_cross_signal_none_when_fast_series_too_short():
    fast = pd.Series([9])
    slow = pd.Series([10, 10])
    assert ema_cross_signal(fast, slow, slope_fast=1.0, slope_threshold=0.05) is None


def test_ema_cross_signal_none_when_slow_series_too_short():
    fast = pd.Series([9, 11])
    slow = pd.Series([10])
    assert ema_cross_signal(fast, slow, slope_fast=1.0, slope_threshold=0.05) is None
