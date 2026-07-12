"""Walk-forward backtest simulation. Iterates 1-minute bars in order,
never looking ahead, generating signals only from closed candles and
managing at most one open position at a time."""
from dataclasses import dataclass, field
from datetime import time as dt_time

import pandas as pd

from backtest.data_loader import resample_to_5min
from indicators.atr import calculate_atr
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend
from risk.risk_manager import (
    TrailingStopTracker,
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
)
from strategy.strategy import generate_signal


@dataclass
class Trade:
    entry_time: pd.Timestamp
    direction: str
    entry_price: float
    quantity: int
    stop_price: float
    target_price: float
    entry_reasons: list[str] = field(default_factory=list)
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None

    @property
    def pnl(self) -> float | None:
        if self.exit_price is None:
            return None
        mult = 1 if self.direction == "BUY_CALL" else -1
        return (self.exit_price - self.entry_price) * mult * self.quantity


class BacktestEngine:
    def __init__(self, df_1m: pd.DataFrame, cfg: dict):
        self.df_1m = df_1m
        self.df_5m = resample_to_5min(df_1m)
        self.cfg = cfg
        self.capital = cfg["backtest"]["initial_capital"]
        self.trades: list[Trade] = []
        self.open_trade: Trade | None = None
        self.tracker: TrailingStopTracker | None = None

        self.current_day = None
        self.trades_today = 0
        self.day_start_capital = self.capital
        self.consecutive_losses = 0
        self.trading_halted_today = False

    def run(self) -> list[Trade]:
        warmup = self.cfg["backtest"]["warmup_bars"]
        for i in range(warmup, len(self.df_1m)):
            window_1m = self.df_1m.iloc[: i + 1]
            now = window_1m.index[-1]
            self._roll_day(now)

            if self.open_trade is not None:
                self._manage_open_trade(window_1m)
                continue

            if self.trading_halted_today or self.trades_today >= self.cfg["risk"]["max_trades_per_day"]:
                continue
            if not self._within_trading_hours(now):
                continue

            # A 5-minute bin is left-labeled (label L covers [L, L+5min)) and
            # only fully closed once `now` reaches L+5min -- filtering by
            # `index <= now` would include the still-forming bin whose label
            # equals `now`'s 5-minute floor, which was aggregated from the
            # full upfront resample and so leaks future 1-minute bars.
            window_5m = self.df_5m[self.df_5m.index + pd.Timedelta(minutes=5) <= now]
            if len(window_5m) < warmup:
                continue

            signal = generate_signal(window_1m, window_5m, self.cfg)
            if signal.direction:
                self._enter_trade(window_1m, signal)

        if self.open_trade is not None:
            self._close_trade(self.df_1m.index[-1], self.df_1m["close"].iloc[-1], "backtest_end")

        return self.trades

    def _roll_day(self, now: pd.Timestamp) -> None:
        day = now.date()
        if self.current_day != day:
            self.current_day = day
            self.trades_today = 0
            self.day_start_capital = self.capital
            self.consecutive_losses = 0
            self.trading_halted_today = False

    def _within_trading_hours(self, now: pd.Timestamp) -> bool:
        t = now.time()
        for start_s, end_s in self.cfg["trading_hours"]["windows"]:
            if dt_time.fromisoformat(start_s) <= t <= dt_time.fromisoformat(end_s):
                return True
        return False

    def _enter_trade(self, window_1m: pd.DataFrame, signal) -> None:
        entry_price = window_1m["close"].iloc[-1]
        prev_candle = window_1m.iloc[-2]
        atr_value = calculate_atr(window_1m, self.cfg["indicators"]["atr_length"]).iloc[-1]
        stop_price = calculate_stop_loss(
            signal.direction, prev_candle, atr_value, self.cfg["risk"]["atr_stop_multiplier"], entry_price
        )
        qty = calculate_position_size(
            self.capital, self.cfg["risk"]["risk_pct"], entry_price, stop_price, self.cfg["instrument"]["lot_size"]
        )
        if qty <= 0:
            return
        target_price = calculate_target(signal.direction, entry_price, stop_price, self.cfg["risk"]["reward_risk_ratio"])

        self.open_trade = Trade(
            entry_time=window_1m.index[-1],
            direction=signal.direction,
            entry_price=entry_price,
            quantity=qty,
            stop_price=stop_price,
            target_price=target_price,
            entry_reasons=signal.reasons,
        )
        self.tracker = TrailingStopTracker(
            signal.direction, entry_price, stop_price, self.cfg["risk"]["breakeven_r"], self.cfg["risk"]["trail_start_r"]
        )
        self.trades_today += 1

    def _manage_open_trade(self, window_1m: pd.DataFrame) -> None:
        now = window_1m.index[-1]
        price = window_1m["close"].iloc[-1]
        direction = self.open_trade.direction

        st_fast = supertrend(window_1m, **self.cfg["indicators"]["supertrend_fast"])
        st_value = st_fast["supertrend"].iloc[-1]
        st_trend = st_fast["trend"].iloc[-1]

        self.open_trade.stop_price = self.tracker.update(price, st_value)

        ind = self.cfg["indicators"]
        ema_fast = calculate_ema(window_1m["close"], ind["ema_fast_length"])
        ema_slow = calculate_ema(window_1m["close"], ind["ema_slow_length"])
        slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
        ema_signal = ema_cross_signal(ema_fast, ema_slow, slope_fast, ind["ema_slope_threshold"])
        ema_reversed = (direction == "BUY_CALL" and ema_signal == "bearish") or (
            direction == "SELL_PUT" and ema_signal == "bullish"
        )

        hit_target = price >= self.open_trade.target_price if direction == "BUY_CALL" else price <= self.open_trade.target_price
        hit_stop = price <= self.open_trade.stop_price if direction == "BUY_CALL" else price >= self.open_trade.stop_price
        st_reversed = (direction == "BUY_CALL" and st_trend == -1) or (direction == "SELL_PUT" and st_trend == 1)
        eod = now.time() >= dt_time.fromisoformat(self.cfg["trading_hours"]["square_off_time"])

        if hit_target:
            self._close_trade(now, self.open_trade.target_price, "target_hit")
        elif hit_stop:
            self._close_trade(now, self.open_trade.stop_price, "stop_hit")
        elif st_reversed:
            self._close_trade(now, price, "supertrend_reversal")
        elif ema_reversed:
            self._close_trade(now, price, "ema_reversal")
        elif eod:
            self._close_trade(now, price, "eod_square_off")

    def _close_trade(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        self.open_trade.exit_time = exit_time
        self.open_trade.exit_price = exit_price
        self.open_trade.exit_reason = reason
        self.trades.append(self.open_trade)

        pnl = self.open_trade.pnl
        self.capital += pnl
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

        daily_loss_pct = (self.day_start_capital - self.capital) / self.day_start_capital * 100
        if self.consecutive_losses >= self.cfg["risk"]["max_consecutive_losses"]:
            self.trading_halted_today = True
        if daily_loss_pct >= self.cfg["risk"]["max_daily_loss_pct"]:
            self.trading_halted_today = True

        self.open_trade = None
        self.tracker = None
