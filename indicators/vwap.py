"""Session-anchored VWAP (resets at the start of each trading day)."""
import pandas as pd


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    tp_vol = typical_price * df["volume"]
    cum_tp_vol = tp_vol.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    return cum_tp_vol / cum_vol


def price_above_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] > vwap_series.iloc[-1]


def price_below_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] < vwap_series.iloc[-1]
