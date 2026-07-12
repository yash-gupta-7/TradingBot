import numpy as np
import pandas as pd

from indicators.adx import calculate_adx, adx_filter_passes


def _trending_df(n=60):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(np.linspace(100, 160, n), index=idx)
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def _choppy_df(n=60):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(100 + np.sin(np.arange(n)) * 0.5, index=idx)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.3,
            "low": close - 0.3,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_adx_in_valid_range():
    df = _trending_df()
    adx = calculate_adx(df, length=14)
    assert (adx.dropna() >= 0).all()
    assert (adx.dropna() <= 100).all()


def test_adx_higher_for_strong_trend_than_choppy_range():
    trending_adx = calculate_adx(_trending_df(), length=14).iloc[-1]
    choppy_adx = calculate_adx(_choppy_df(), length=14).iloc[-1]
    assert trending_adx > choppy_adx


def test_adx_filter_passes_true_for_strong_trend():
    assert adx_filter_passes(_trending_df(), length=14, threshold=25) is True


def test_adx_filter_passes_false_for_choppy_range():
    assert adx_filter_passes(_choppy_df(), length=14, threshold=25) is False
