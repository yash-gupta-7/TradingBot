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
    """Bullish: fast EMA above slow EMA AND fast slope >= threshold.
    Bearish: fast EMA below slow EMA AND fast slope <= -threshold.
    State-based (checked fresh every bar), not a one-bar crossover event --
    a one-bar event almost never lands on the same bar as the other
    state-based filters (SuperTrend/ADX/ATR/volume/VWAP), so combining them
    with AND effectively never fires."""
    if len(fast) < 1 or len(slow) < 1:
        return None
    if fast.iloc[-1] > slow.iloc[-1] and slope_fast >= slope_threshold:
        return "bullish"
    if fast.iloc[-1] < slow.iloc[-1] and slope_fast <= -slope_threshold:
        return "bearish"
    return None
