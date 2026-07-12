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
