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


def pytest_approx(x, tol=1e-6):
    import pytest

    return pytest.approx(x, abs=tol)


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


def test_compute_metrics_drawdown_sharpe_expectancy():
    # pnls: [400, -200, 600]
    # equity_curve: [400, 200, 800]
    # running_max: [400, 400, 800]
    # drawdowns: [0, 200, 0]
    # max_drawdown: 200 (peak 400 to trough 200)
    trades = [
        _trade("2026-01-05 10:00", "2026-01-05 10:30", "BUY_CALL", 100, 120),  # +400
        _trade("2026-01-05 11:00", "2026-01-05 11:20", "BUY_CALL", 100, 90),  # -200
        _trade("2026-01-06 10:00", "2026-01-06 10:30", "BUY_CALL", 100, 130),  # +600
    ]
    m = compute_metrics(trades)

    # max_drawdown: max of (running_max - equity_curve)
    assert m["max_drawdown"] == pytest_approx(200.0)

    # sharpe_ratio = mean(pnls) / std(pnls) * sqrt(len(pnls))
    # mean = 800/3, std ≈ 339.932, sqrt(3) ≈ 1.732 → ≈ 1.1094
    assert m["sharpe_ratio"] == pytest_approx(1.1094, tol=1e-3)

    # average_trade = mean(pnls) = 800/3 ≈ 266.667
    assert m["average_trade"] == pytest_approx(800 / 3)

    # expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
    # = (2/3) * 500 + (1/3) * (-200) = 800/3 ≈ 266.667
    # (expectancy must equal average_trade for this input)
    assert m["expectancy"] == pytest_approx(800 / 3)


def test_compute_metrics_drawdown_underwater_from_start():
    # pnls: [-100, 50]
    # equity_from_zero (seeded with 0 baseline): [0, -100, -50]
    # running_max: [0, 0, 0]
    # drawdowns: [0, 100, 50]
    # max_drawdown: 100 (peak 0 to trough -100, i.e. losing from account inception)
    trades = [
        _trade("2026-01-05 10:00", "2026-01-05 10:30", "BUY_CALL", 100, 95),  # -100
        _trade("2026-01-05 11:00", "2026-01-05 11:20", "BUY_CALL", 100, 102.5),  # +50
    ]
    m = compute_metrics(trades)
    assert m["max_drawdown"] == pytest_approx(100.0)


def test_compute_metrics_monthly_returns_single_month():
    # All trades in same month; monthly_returns should be {"2026-01": 800.0}
    trades = [
        _trade("2026-01-05 10:00", "2026-01-05 10:30", "BUY_CALL", 100, 120),  # +400
        _trade("2026-01-05 11:00", "2026-01-05 11:20", "BUY_CALL", 100, 90),  # -200
        _trade("2026-01-06 10:00", "2026-01-06 10:30", "BUY_CALL", 100, 130),  # +600
    ]
    m = compute_metrics(trades)

    assert m["monthly_returns"] == {"2026-01": pytest_approx(800.0)}


def test_compute_metrics_monthly_returns_multi_month():
    # Trades spanning Jan and Feb
    # Jan (exit_time 2026-01-31): +500
    # Feb (exit_time 2026-02-01, 2026-02-28): +300 + (-200) = +100
    # monthly_returns: {"2026-01": 500, "2026-02": 100}
    trades = [
        _trade("2026-01-31 10:00", "2026-01-31 10:30", "BUY_CALL", 100, 125),  # +500
        _trade("2026-02-01 10:00", "2026-02-01 10:30", "BUY_CALL", 100, 115),  # +300
        _trade("2026-02-28 10:00", "2026-02-28 10:30", "BUY_CALL", 100, 90),  # -200
    ]
    m = compute_metrics(trades)

    assert len(m["monthly_returns"]) == 2
    assert m["monthly_returns"]["2026-01"] == pytest_approx(500.0)
    assert m["monthly_returns"]["2026-02"] == pytest_approx(100.0)


def test_compute_metrics_handles_no_trades_gracefully():
    m = compute_metrics([])
    assert m["win_rate"] == 0
    assert m["profit_factor"] == 0
    assert m["equity_curve"] == []
