"""Wilder's ADX (trend strength) and its threshold filter."""
import numpy as np
import pandas as pd

from indicators.atr import true_range


def calculate_adx(df: pd.DataFrame, length: int) -> pd.Series:
    high, low = df["high"], df["low"]
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr = tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1 / length, min_periods=length, adjust=False
    ).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1 / length, min_periods=length, adjust=False
    ).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def adx_filter_passes(df: pd.DataFrame, length: int, threshold: float) -> bool:
    adx = calculate_adx(df, length)
    if pd.isna(adx.iloc[-1]):
        return False
    return bool(adx.iloc[-1] > threshold)
