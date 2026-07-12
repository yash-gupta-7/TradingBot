import pandas as pd

from backtest.engine import Trade
from backtest.metrics import compute_metrics


def _trade(entry_time, exit_time, direction, entry_price, exit_price, qty=20):
    return Trade(
        entry_time=pd.Timestamp(entry_time),
        direction=direction,
        entry_price=entry_price,
        quantity=qty,
        stop_price=entry_price - 10 if direction == "BUY_CALL" else entry_price + 10,
        target_price=entry_price + 20 if direction == "BUY_CALL" else entry_price - 20,
        exit_time=pd.Timestamp(exit_time),
        exit_price=exit_price,
        exit_reason="target_hit",
    )


def test_compute_metrics_win_rate_and_profit_factor():
    trades = [
        _trade("2026-01-05 10:00", "2026-01-05 10:30", "BUY_CALL", 100, 120),  # +400
        _trade("2026-01-05 11:00", "2026-01-05 11:20", "BUY_CALL", 100, 90),  # -200
        _trade("2026-01-06 10:00", "2026-01-06 10:30", "BUY_CALL", 100, 130),  # +600
    ]
    m = compute_metrics(trades)
    assert m["win_rate"] == pytest_approx(2 / 3)
    assert m["profit_factor"] == pytest_approx(1000 / 200)
    assert len(m["equity_curve"]) == 3
    assert m["max_consecutive_wins"] == 1
    assert m["max_consecutive_losses"] == 1


def pytest_approx(x, tol=1e-6):
    import pytest

    return pytest.approx(x, abs=tol)


def test_compute_metrics_handles_no_trades_gracefully():
    m = compute_metrics([])
    assert m["win_rate"] == 0
    assert m["profit_factor"] == 0
    assert m["equity_curve"] == []
