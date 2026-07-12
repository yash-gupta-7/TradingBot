"""Position sizing, stop-loss selection, and target calculation.

Shared by the backtester (Phase 1) and, unmodified, by live/paper order
execution (Phase 2) — this module never places orders itself.
"""
import pandas as pd


def calculate_stop_loss(
    direction: str,
    prev_candle: pd.Series,
    atr_value: float,
    atr_multiplier: float,
    entry_price: float,
) -> float:
    """Always take whichever stop is further from entry (more room before
    a premature stop-out) between the previous candle's extreme and an
    ATR-multiple stop. See plan Global Constraints for the "larger stop"
    interpretation."""
    if direction == "BUY_CALL":
        prev_stop = prev_candle["low"]
        atr_stop = entry_price - atr_multiplier * atr_value
        return min(prev_stop, atr_stop)
    prev_stop = prev_candle["high"]
    atr_stop = entry_price + atr_multiplier * atr_value
    return max(prev_stop, atr_stop)


def calculate_position_size(
    capital: float, risk_pct: float, entry_price: float, stop_price: float, lot_size: int
) -> int:
    """Quantity = risk amount / stop distance, rounded down to whole lots."""
    risk_amount = capital * (risk_pct / 100)
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0
    raw_qty = risk_amount / stop_distance
    lots = int(raw_qty // lot_size)
    return max(lots, 0) * lot_size


def calculate_target(direction: str, entry_price: float, stop_price: float, rr_ratio: float) -> float:
    risk = abs(entry_price - stop_price)
    reward = risk * rr_ratio
    return entry_price + reward if direction == "BUY_CALL" else entry_price - reward
