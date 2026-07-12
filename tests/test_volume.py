import pandas as pd

from indicators.volume import volume_confirms


def _df_with_volumes(volumes):
    return pd.DataFrame({"volume": volumes})


def test_volume_confirms_true_on_breakout_spike():
    volumes = [100] * 20 + [200]  # last bar is 2x the prior 20-bar average
    df = _df_with_volumes(volumes)
    assert volume_confirms(df, lookback=20, multiplier=1.5) is True


def test_volume_confirms_false_on_average_volume():
    volumes = [100] * 20 + [110]
    df = _df_with_volumes(volumes)
    assert volume_confirms(df, lookback=20, multiplier=1.5) is False
