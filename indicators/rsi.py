"""Wilder's RSI and midline-cross signal."""
import pandas as pd


def calculate_rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def rsi_signal(rsi_series: pd.Series, midline: float) -> str | None:
    """Bullish: crossed above midline AND still rising.
    Bearish: crossed below midline AND still falling.
    Overbought/oversold zones are intentionally NOT used to generate
    signals here — per spec they're confirmation-only, applied in strategy.py."""
    if len(rsi_series) < 2:
        return None
    crossed_above = rsi_series.iloc[-2] <= midline and rsi_series.iloc[-1] > midline
    crossed_below = rsi_series.iloc[-2] >= midline and rsi_series.iloc[-1] < midline
    rising = rsi_series.iloc[-1] > rsi_series.iloc[-2]
    falling = rsi_series.iloc[-1] < rsi_series.iloc[-2]
    if crossed_above and rising:
        return "bullish"
    if crossed_below and falling:
        return "bearish"
    return None
