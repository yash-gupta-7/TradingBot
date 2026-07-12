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
