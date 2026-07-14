"""SuperTrend indicator (standard recursive-band algorithm) and the
two-instance agreement check used as the primary trend filter."""
import numpy as np
import pandas as pd

from indicators.atr import calculate_atr


def supertrend(df: pd.DataFrame, length: int, multiplier: float) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    atr = calculate_atr(df, length)
    hl2 = (high + low) / 2

    upperband = (hl2 + multiplier * atr).to_numpy()
    lowerband = (hl2 - multiplier * atr).to_numpy()
    close_arr = close.to_numpy()
    n = len(df)
    final_upper = upperband.copy()
    final_lower = lowerband.copy()

    # ponytail: recursive band still needs a Python loop (pandas can't
    # vectorize a value depending on its own previous value), but numpy
    # array access instead of Series.iloc cuts per-step cost ~50-100x.
    # The walk-forward backtest reruns this on a growing window every bar,
    # so the old iloc version was O(n^2) with a heavy constant -- that's
    # what made an 8000+ candle backtest look stuck for the better part
    # of an hour instead of finishing in seconds.
    for i in range(1, n):
        if close_arr[i - 1] <= final_upper[i - 1]:
            final_upper[i] = min(upperband[i], final_upper[i - 1])
        else:
            final_upper[i] = upperband[i]

        if close_arr[i - 1] >= final_lower[i - 1]:
            final_lower[i] = max(lowerband[i], final_lower[i - 1])
        else:
            final_lower[i] = lowerband[i]

    trend = np.empty(n, dtype=int)
    trend[0] = 1
    for i in range(1, n):
        if trend[i - 1] == 1 and close_arr[i] < final_lower[i]:
            trend[i] = -1
        elif trend[i - 1] == -1 and close_arr[i] > final_upper[i]:
            trend[i] = 1
        else:
            trend[i] = trend[i - 1]

    line = np.where(trend == 1, final_lower, final_upper)
    return pd.DataFrame({"supertrend": line, "trend": trend}, index=df.index)


def supertrend_agree(trend_a: int, trend_b: int) -> str | None:
    if trend_a == 1 and trend_b == 1:
        return "bullish"
    if trend_a == -1 and trend_b == -1:
        return "bearish"
    return None
