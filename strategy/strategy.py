"""Combine all 7 indicators into a single entry signal per the spec's
ALL-conditions-must-agree rule. Callers must pass DataFrames containing
only closed candles (the last row is the most recently closed bar)."""
from dataclasses import dataclass, field

import pandas as pd

from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend, supertrend_agree


@dataclass
class Signal:
    direction: str | None
    reasons: list[str] = field(default_factory=list)


def _higher_timeframe_trend(df_5m: pd.DataFrame, cfg: dict) -> str | None:
    st_cfg = cfg["indicators"]
    st1 = supertrend(df_5m, **st_cfg["supertrend_fast"])
    st2 = supertrend(df_5m, **st_cfg["supertrend_slow"])
    return supertrend_agree(st1["trend"].iloc[-1], st2["trend"].iloc[-1])


def generate_signal(df_1m: pd.DataFrame, df_5m: pd.DataFrame, cfg: dict) -> Signal:
    ind = cfg["indicators"]

    higher_trend = _higher_timeframe_trend(df_5m, cfg)
    if higher_trend is None:
        return Signal(direction=None, reasons=["higher timeframe trend undecided"])

    st1 = supertrend(df_1m, **ind["supertrend_fast"])
    st2 = supertrend(df_1m, **ind["supertrend_slow"])
    st_trend = supertrend_agree(st1["trend"].iloc[-1], st2["trend"].iloc[-1])
    if st_trend != higher_trend:
        return Signal(direction=None, reasons=["1-minute SuperTrend disagrees with higher timeframe"])

    ema_fast = calculate_ema(df_1m["close"], ind["ema_fast_length"])
    ema_slow = calculate_ema(df_1m["close"], ind["ema_slow_length"])
    slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
    ema_signal = ema_cross_signal(ema_fast, ema_slow, slope_fast, ind["ema_slope_threshold"])
    if ema_signal != st_trend:
        return Signal(direction=None, reasons=["no EMA crossover matching trend direction"])

    direction = "BUY_CALL" if st_trend == "bullish" else "SELL_PUT"
    reasons = [
        f"higher timeframe trend: {higher_trend}",
        f"dual SuperTrend agrees: {st_trend}",
        f"EMA{ind['ema_fast_length']}/EMA{ind['ema_slow_length']} cross: {ema_signal} (slope={slope_fast:.4f})",
    ]
    return Signal(direction=direction, reasons=reasons)
