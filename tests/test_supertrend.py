import numpy as np
import pandas as pd

from indicators.supertrend import supertrend, supertrend_agree


def _uptrend_df(n=50):
    idx = pd.date_range("2026-01-05 09:15", periods=n, freq="1min")
    close = pd.Series(np.linspace(100, 150, n), index=idx)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": 1000,
        },
        index=idx,
    )


def test_supertrend_columns_present():
    df = _uptrend_df()
    result = supertrend(df, length=10, multiplier=3)
    assert "supertrend" in result.columns
    assert "trend" in result.columns
    assert set(result["trend"].dropna().unique()).issubset({1, -1})


def test_supertrend_trend_is_up_in_sustained_uptrend():
    df = _uptrend_df()
    result = supertrend(df, length=10, multiplier=3)
    assert result["trend"].iloc[-1] == 1
    assert result["supertrend"].iloc[-1] < df["close"].iloc[-1]


def test_supertrend_agree_bullish_when_both_up():
    assert supertrend_agree(1, 1) == "bullish"


def test_supertrend_agree_bearish_when_both_down():
    assert supertrend_agree(-1, -1) == "bearish"


def test_supertrend_agree_none_when_disagreeing():
    assert supertrend_agree(1, -1) is None
