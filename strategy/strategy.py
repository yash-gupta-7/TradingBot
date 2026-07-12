"""Combine all 7 indicators into a single entry signal per the spec's
ALL-conditions-must-agree rule. Callers must pass DataFrames containing
only closed candles (the last row is the most recently closed bar)."""
from dataclasses import dataclass, field

import pandas as pd

from indicators.adx import adx_filter_passes
from indicators.atr import atr_filter_passes
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.rsi import calculate_rsi, rsi_signal
from indicators.supertrend import supertrend, supertrend_agree
from indicators.volume import volume_confirms
from indicators.vwap import calculate_vwap, price_above_vwap, price_below_vwap


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

    rsi = calculate_rsi(df_1m["close"], ind["rsi_length"])
    rsi_sig = rsi_signal(rsi, ind["rsi_midline"])
    if rsi_sig != st_trend:
        return Signal(direction=None, reasons=["RSI midline signal disagrees with trend"])

    if not adx_filter_passes(df_1m, ind["adx_length"], ind["adx_threshold"]):
        return Signal(direction=None, reasons=["ADX below trend-strength threshold"])

    if not atr_filter_passes(df_1m, ind["atr_length"], ind["atr_sma_length"]):
        return Signal(direction=None, reasons=["ATR below its own moving average (low volatility)"])

    if not volume_confirms(df_1m, ind["volume_lookback"], ind["volume_multiplier"]):
        return Signal(direction=None, reasons=["volume did not confirm breakout"])

    vwap = calculate_vwap(df_1m)
    if st_trend == "bullish" and not price_above_vwap(df_1m, vwap):
        return Signal(direction=None, reasons=["price not above VWAP"])
    if st_trend == "bearish" and not price_below_vwap(df_1m, vwap):
        return Signal(direction=None, reasons=["price not below VWAP"])

    direction = "BUY_CALL" if st_trend == "bullish" else "SELL_PUT"
    reasons = [
        f"higher timeframe trend: {higher_trend}",
        f"dual SuperTrend agrees: {st_trend}",
        f"EMA{ind['ema_fast_length']}/EMA{ind['ema_slow_length']} cross: {ema_signal} (slope={slope_fast:.4f})",
        f"RSI midline signal: {rsi_sig}",
        "ADX confirms trend strength",
        "ATR confirms sufficient volatility",
        "volume confirms breakout",
        f"price {'above' if st_trend == 'bullish' else 'below'} VWAP",
    ]
    return Signal(direction=direction, reasons=reasons)
