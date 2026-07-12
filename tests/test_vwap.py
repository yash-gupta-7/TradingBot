import pandas as pd

from indicators.vwap import calculate_vwap, price_above_vwap, price_below_vwap


def _two_day_df():
    idx = pd.date_range("2026-01-05 09:15", periods=4, freq="1min").append(
        pd.date_range("2026-01-06 09:15", periods=4, freq="1min")
    )
    return pd.DataFrame(
        {
            "high": [105, 106, 107, 108] * 2,
            "low": [95, 96, 97, 98] * 2,
            "close": [100, 101, 102, 103] * 2,
            "volume": [10, 20, 10, 20] * 2,
        },
        index=idx,
    )


def test_vwap_resets_each_session():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    # first bar of day 2 should equal that bar's own typical price,
    # not be dragged down by day 1's cumulative average
    day2_first_typical = (df["high"].iloc[4] + df["low"].iloc[4] + df["close"].iloc[4]) / 3
    assert abs(vwap.iloc[4] - day2_first_typical) < 1e-9


def test_vwap_within_session_high_low_range():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    assert (vwap >= df["low"]).all()
    assert (vwap <= df["high"]).all()


def test_price_above_and_below_vwap():
    df = _two_day_df()
    vwap = calculate_vwap(df)
    assert price_above_vwap(df, vwap) == (df["close"].iloc[-1] > vwap.iloc[-1])
    assert price_below_vwap(df, vwap) == (df["close"].iloc[-1] < vwap.iloc[-1])
