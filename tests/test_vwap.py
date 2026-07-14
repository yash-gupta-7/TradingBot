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


def test_vwap_falls_back_to_unweighted_average_when_volume_is_zero():
    # Index instruments (SENSEX/NIFTY) report zero volume -- the
    # volume-weighted formula is 0/0 and must not collapse to NaN.
    idx = pd.date_range("2026-01-05 09:15", periods=3, freq="1min")
    df = pd.DataFrame(
        {"high": [105, 106, 107], "low": [95, 96, 97], "close": [100, 102, 104], "volume": [0, 0, 0]},
        index=idx,
    )
    vwap = calculate_vwap(df)
    assert not vwap.isna().any()
    typical = (df["high"] + df["low"] + df["close"]) / 3
    expected_last = typical.expanding().mean().iloc[-1]
    assert abs(vwap.iloc[-1] - expected_last) < 1e-9
