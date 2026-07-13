"""Standard backtest performance statistics computed from a closed-trade list."""
import numpy as np
import pandas as pd

from backtest.engine import Trade


def compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "win_rate": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "average_trade": 0,
            "expectancy": 0,
            "equity_curve": [],
            "monthly_returns": {},
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
        }

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    win_rate = len(wins) / len(pnls)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    equity_curve = list(np.cumsum(pnls))
    # Seed with a 0 baseline so a losing streak from account inception counts
    # toward drawdown (equity_curve itself is unseeded to preserve its len(trades) contract).
    equity_from_zero = np.concatenate(([0.0], equity_curve))
    running_max = np.maximum.accumulate(equity_from_zero)
    drawdowns = running_max - equity_from_zero
    max_drawdown = float(drawdowns.max()) if len(drawdowns) else 0

    returns = pd.Series(pnls)
    sharpe_ratio = float(returns.mean() / returns.std() * np.sqrt(len(returns))) if returns.std() > 0 else 0

    average_trade = float(np.mean(pnls))
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    months = pd.Series(pnls, index=[t.exit_time for t in trades])
    monthly_returns = months.groupby(months.index.to_period("M")).sum().to_dict()
    monthly_returns = {str(k): float(v) for k, v in monthly_returns.items()}

    max_consecutive_wins = _max_consecutive(pnls, lambda p: p > 0)
    max_consecutive_losses = _max_consecutive(pnls, lambda p: p <= 0)

    return {
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "average_trade": average_trade,
        "expectancy": expectancy,
        "equity_curve": equity_curve,
        "monthly_returns": monthly_returns,
        "max_consecutive_wins": max_consecutive_wins,
        "max_consecutive_losses": max_consecutive_losses,
    }


def _max_consecutive(pnls: list[float], predicate) -> int:
    best = current = 0
    for p in pnls:
        if predicate(p):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
