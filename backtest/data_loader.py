"""Historical candle fetch (Kite) and timeframe resampling."""
from datetime import datetime, timedelta

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


def fetch_with_warmup(
    kite: KiteConnect,
    instrument_token: int,
    from_date: str,
    to_date: str,
    warmup_days: int = 7,
    interval: str = "minute",
) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Fetch candles with extra prior-day data prepended for indicator pre-seeding.

    Fetches `warmup_days` calendar days before `from_date` so that all
    indicators (EMA, SuperTrend, ATR) are fully warm by 09:15 on the first
    live trading day — no intra-day warmup delay needed.

    Args:
        warmup_days: Calendar days to look back. 7 days safely covers a full
                     trading week even across weekends and public holidays.

    Returns:
        (df_full, live_from) where:
          - df_full   : combined DataFrame of warmup + live bars, sorted by time.
          - live_from : pd.Timestamp of midnight on from_date. The engine uses
                        this to skip signal generation on warmup-only bars.
    """
    pre_start = (
        datetime.strptime(from_date, "%Y-%m-%d") - timedelta(days=warmup_days)
    ).strftime("%Y-%m-%d")

    df_full = fetch_historical(kite, instrument_token, pre_start, to_date, interval)
    live_from = pd.Timestamp(from_date)
    return df_full, live_from


def resample_to_5min(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-minute OHLCV candles into 5-minute candles."""
    df_5m = df_1m.resample("5min").agg(_AGG)
    return df_5m.dropna(subset=["open"])
