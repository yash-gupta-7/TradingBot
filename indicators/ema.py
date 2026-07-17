"""EMA calculation, slope, and crossover signal."""
import pandas as pd


def calculate_ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def ema_slope(ema_series: pd.Series, lookback: int) -> float:
    """Average price-points change per bar over `lookback` bars."""
    if len(ema_series) < lookback + 1:
        return 0.0
    return (ema_series.iloc[-1] - ema_series.iloc[-1 - lookback]) / lookback


def ema_cross_signal(
    fast: pd.Series,
    slow: pd.Series,
    slope_fast: float,
    slope_slow: float,
    slope_threshold: float,
) -> str | None:
    """Return the EMA trend signal when ALL of the following hold:

    Bullish (both EMAs rising, fast stacked above slow):
      • fast EMA > slow EMA  (correct stacking — fast above slow)
      • slope_fast >= +threshold  (EMA9 angling upward steeply enough)
      • slope_slow >= +threshold  (EMA15 also angling upward)

    Bearish (both EMAs falling, fast stacked below slow):
      • fast EMA < slow EMA  (correct stacking — fast below slow)
      • slope_fast <= -threshold  (EMA9 angling downward steeply enough)
      • slope_slow <= -threshold  (EMA15 also angling downward)

    Returns None when EMAs are flat, diverging, or have opposite slopes.

    The `slope_threshold` is in price-points per bar.  A value of 5.0 on
    SENSEX 1-min data corresponds to roughly a 25° visual angle on a
    standard chart (see config comment for tuning guidance).
    """
    if len(fast) < 1 or len(slow) < 1:
        return None

    fast_val = fast.iloc[-1]
    slow_val = slow.iloc[-1]

    if (fast_val > slow_val
            and slope_fast >= slope_threshold
            and slope_slow >= slope_threshold):
        return "bullish"

    if (fast_val < slow_val
            and slope_fast <= -slope_threshold
            and slope_slow <= -slope_threshold):
        return "bearish"

    return None
