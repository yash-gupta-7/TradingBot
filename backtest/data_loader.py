"""Historical candle fetch (Kite) and timeframe resampling."""
import pandas as pd
from kiteconnect import KiteConnect

_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def fetch_historical(
    kite: KiteConnect,
    instrument_token: int,
    from_date: str,
    to_date: str,
    interval: str = "minute",
) -> pd.DataFrame:
    """Fetch OHLCV candles from Kite's historical data API.

    from_date/to_date: "YYYY-MM-DD" strings.
    """
    candles = kite.historical_data(instrument_token, from_date, to_date, interval)
    if not candles:
        # Pre-market or holiday — return empty DataFrame with proper DatetimeIndex
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], name="datetime")
        )
    df = pd.DataFrame(candles)
    df = df.rename(columns={"date": "datetime"}).set_index("datetime")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["open", "high", "low", "close", "volume"]]


def resample_to_5min(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute OHLCV candles into 5-minute candles."""
    df_5m = df_1m.resample("5min").agg(_AGG)
    return df_5m.dropna(subset=["open"])
