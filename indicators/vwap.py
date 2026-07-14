"""Session-anchored VWAP (resets at the start of each trading day)."""
import pandas as pd


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    day = df.index.normalize()
    tp_vol = typical_price * df["volume"]
    cum_tp_vol = tp_vol.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    vwap = cum_tp_vol / cum_vol

    # Index instruments (SENSEX/NIFTY) report zero volume in Kite's
    # historical API, making the volume-weighted average a 0/0 NaN for the
    # whole session. Fall back to an unweighted cumulative average of
    # typical price -- the natural volume-agnostic analog of the same
    # "session average price" benchmark -- instead of leaving it undefined.
    cum_count = typical_price.groupby(day).cumcount() + 1
    unweighted = typical_price.groupby(day).cumsum() / cum_count
    return vwap.where(cum_vol != 0, unweighted)


def price_above_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] > vwap_series.iloc[-1]


def price_below_vwap(df: pd.DataFrame, vwap_series: pd.Series) -> bool:
    return df["close"].iloc[-1] < vwap_series.iloc[-1]
