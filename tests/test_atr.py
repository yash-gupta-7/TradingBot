import pandas as pd

from indicators.atr import true_range, calculate_atr, atr_filter_passes


def _flat_df(n=30, price=100.0):
    return pd.DataFrame(
        {
            "open": [price] * n,
            "high": [price] * n,
            "low": [price] * n,
            "close": [price] * n,
            "volume": [1000] * n,
        }
    )


def test_true_range_zero_for_flat_series():
    df = _flat_df()
    tr = true_range(df)
    assert (tr.fillna(0) == 0).all()


def test_atr_non_negative_on_volatile_series():
    df = _flat_df(30)
    df.loc[10:, "high"] += 5
    df.loc[10:, "low"] -= 5
    atr = calculate_atr(df, length=14)
    assert (atr.dropna() >= 0).all()
    assert atr.iloc[-1] > 0


def test_atr_filter_passes_true_when_recent_volatility_spikes():
    df = _flat_df(40)
    df.loc[35:, "high"] += 10
    df.loc[35:, "low"] -= 10
    assert atr_filter_passes(df, length=14, sma_length=14) is True


def test_atr_filter_passes_false_on_flat_series():
    df = _flat_df(40)
    assert atr_filter_passes(df, length=14, sma_length=14) is False
