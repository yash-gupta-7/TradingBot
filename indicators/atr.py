"""Wilder's True Range / ATR and the ATR-vs-ATR-SMA volatility filter."""
import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    ranges = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    )
    return ranges.max(axis=1)


def calculate_atr(df: pd.DataFrame, length: int) -> pd.Series:
    tr = true_range(df)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def atr_filter_passes(df: pd.DataFrame, length: int, sma_length: int) -> bool:
    """True only when current volatility (ATR) exceeds its own moving
    average — rejects low-volatility, choppy conditions."""
    atr = calculate_atr(df, length)
    atr_sma = atr.rolling(sma_length).mean()
    if pd.isna(atr.iloc[-1]) or pd.isna(atr_sma.iloc[-1]):
        return False
    return bool(atr.iloc[-1] > atr_sma.iloc[-1])
