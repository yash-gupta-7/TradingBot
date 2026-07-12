"""Breakout volume confirmation: current bar vs the trailing average."""
import pandas as pd


def volume_confirms(df: pd.DataFrame, lookback: int, multiplier: float) -> bool:
    """True when the latest bar's volume exceeds `multiplier`x the average
    of the preceding `lookback` bars (excluding the latest bar itself)."""
    if len(df) < lookback + 1:
        return False
    avg_volume = df["volume"].iloc[-lookback - 1 : -1].mean()
    return bool(df["volume"].iloc[-1] > multiplier * avg_volume)
