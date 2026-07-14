"""Breakout volume confirmation: current bar vs the trailing average."""
import pandas as pd


def volume_confirms(df: pd.DataFrame, lookback: int, multiplier: float) -> bool:
    """True when the latest bar's volume exceeds `multiplier`x the average
    of the preceding `lookback` bars (excluding the latest bar itself).
    Index instruments (e.g. SENSEX/NIFTY) report zero volume in Kite's
    historical API -- there's no real baseline to confirm a breakout
    against, so a zero baseline is treated as non-blocking rather than a
    permanent `0 > 0` failure."""
    if len(df) < lookback + 1:
        return False
    avg_volume = df["volume"].iloc[-lookback - 1 : -1].mean()
    if avg_volume == 0:
        return True
    return bool(df["volume"].iloc[-1] > multiplier * avg_volume)
