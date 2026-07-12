import pandas as pd

from backtest.data_loader import resample_to_5min


def _make_1m_df(n_minutes=10, start="2026-01-05 09:15:00"):
    idx = pd.date_range(start, periods=n_minutes, freq="1min")
    data = {
        "open": range(100, 100 + n_minutes),
        "high": [o + 1 for o in range(100, 100 + n_minutes)],
        "low": [o - 1 for o in range(100, 100 + n_minutes)],
        "close": [o + 0.5 for o in range(100, 100 + n_minutes)],
        "volume": [10] * n_minutes,
    }
    return pd.DataFrame(data, index=idx)


def test_resample_to_5min_aggregates_ohlcv_correctly():
    df_1m = _make_1m_df(10)
    df_5m = resample_to_5min(df_1m)

    assert len(df_5m) == 2
    first_bar = df_5m.iloc[0]
    assert first_bar["open"] == df_1m["open"].iloc[0]
    assert first_bar["high"] == df_1m["high"].iloc[0:5].max()
    assert first_bar["low"] == df_1m["low"].iloc[0:5].min()
    assert first_bar["close"] == df_1m["close"].iloc[4]
    assert first_bar["volume"] == df_1m["volume"].iloc[0:5].sum()
