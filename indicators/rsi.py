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
    """Bullish: RSI above midline. Bearish: RSI below midline.
    State-based (checked fresh every bar), not a one-bar crossover event --
    see ema_cross_signal for why: a one-bar event almost never coincides
    with the other state-based filters.
    Overbought/oversold zones are intentionally NOT used to generate
    signals here — per spec they're confirmation-only, applied in strategy.py."""
    if len(rsi_series) < 1 or pd.isna(rsi_series.iloc[-1]):
        return None
    if rsi_series.iloc[-1] > midline:
        return "bullish"
    if rsi_series.iloc[-1] < midline:
        return "bearish"
    return None
