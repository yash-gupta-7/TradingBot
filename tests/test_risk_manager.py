import pandas as pd

from risk.risk_manager import calculate_stop_loss, calculate_position_size, calculate_target, TrailingStopTracker


def test_stop_loss_buy_uses_wider_of_prev_low_and_atr_stop():
    prev_candle = pd.Series({"low": 98.0, "high": 103.0})
    # ATR stop = 100 - 1.5*3 = 95.5, wider (lower) than prev_low 98 -> use ATR stop
    stop = calculate_stop_loss("BUY_CALL", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 95.5


def test_stop_loss_buy_uses_prev_low_when_tighter_atr_stop():
    prev_candle = pd.Series({"low": 90.0, "high": 103.0})
    # ATR stop = 100 - 1.5*3 = 95.5, prev_low 90 is wider -> use prev_low
    stop = calculate_stop_loss("BUY_CALL", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 90.0


def test_stop_loss_sell_uses_wider_of_prev_high_and_atr_stop():
    prev_candle = pd.Series({"low": 97.0, "high": 101.0})
    # ATR stop = 100 + 1.5*3 = 104.5, wider (higher) than prev_high 101 -> use ATR stop
    stop = calculate_stop_loss("SELL_PUT", prev_candle, atr_value=3.0, atr_multiplier=1.5, entry_price=100.0)
    assert stop == 104.5


def test_position_size_respects_risk_amount_and_lot_size():
    # capital 100000, risk 1% = 1000, stop distance 10, lot_size 20
    # raw qty = 100, already a multiple of lot_size 20 -> 100
    qty = calculate_position_size(100000, 1.0, entry_price=100.0, stop_price=90.0, lot_size=20)
    assert qty == 100


def test_position_size_rounds_down_to_whole_lots():
    # raw qty = 1000/12 = 83.3 -> lots = 4 (4*20=80), rounds down
    qty = calculate_position_size(100000, 1.0, entry_price=100.0, stop_price=88.0, lot_size=20)
    assert qty == 80


def test_target_buy_is_entry_plus_rr_times_risk():
    target = calculate_target("BUY_CALL", entry_price=100.0, stop_price=90.0, rr_ratio=2.0)
    assert target == 120.0


def test_target_sell_is_entry_minus_rr_times_risk():
    target = calculate_target("SELL_PUT", entry_price=100.0, stop_price=110.0, rr_ratio=2.0)
    assert target == 80.0


def test_trailing_stop_moves_to_breakeven_at_1r():
    # entry 100, stop 90 -> 1R = 10. Price at 110 = 1R reached.
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    stop = tracker.update(price=110.0, supertrend_fast_value=95.0)
    assert stop == 100.0  # moved to cost, not yet trailing


def test_trailing_stop_trails_via_supertrend_after_1_5r():
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=110.0, supertrend_fast_value=95.0)  # 1R: breakeven
    stop = tracker.update(price=115.0, supertrend_fast_value=108.0)  # 1.5R: trail
    assert stop == 108.0


def test_trailing_stop_never_moves_backward_for_buy():
    tracker = TrailingStopTracker("BUY_CALL", entry_price=100.0, initial_stop=90.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=115.0, supertrend_fast_value=108.0)  # trailing active, stop=108
    stop = tracker.update(price=116.0, supertrend_fast_value=105.0)  # supertrend dipped
    assert stop == 108.0  # does not retreat


def test_trailing_stop_sell_put_direction():
    tracker = TrailingStopTracker("SELL_PUT", entry_price=100.0, initial_stop=110.0, breakeven_r=1.0, trail_start_r=1.5)
    tracker.update(price=90.0, supertrend_fast_value=95.0)  # 1R down: breakeven
    stop = tracker.update(price=85.0, supertrend_fast_value=92.0)  # 1.5R: trail
    assert stop == 92.0
