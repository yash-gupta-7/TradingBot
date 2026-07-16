import logging
from datetime import datetime, time as dt_time
import pandas as pd

from backtest.data_loader import resample_to_5min
from backtest.engine import Trade
from risk.risk_manager import (
    TrailingStopTracker,
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
)
from strategy.strategy import generate_signal

logger = logging.getLogger(__name__)


class PaperEngine:
    def __init__(self, instrument_token: int, df_1m: pd.DataFrame, cfg: dict):
        self.instrument_token = instrument_token
        self.cfg = cfg
        
        self.df_1m = df_1m.copy()
        if hasattr(self.df_1m.index, 'tz') and self.df_1m.index.tz is not None:
            self.df_1m.index = self.df_1m.index.tz_localize(None)
        self.df_5m = resample_to_5min(self.df_1m)
        
        self.capital = cfg["backtest"]["initial_capital"]
        self.trades: list[Trade] = []
        self.open_trade: Trade | None = None
        self.tracker: TrailingStopTracker | None = None
        
        self.current_day = datetime.now().date()
        self.trades_today = 0
        self.day_start_capital = self.capital
        self.consecutive_losses = 0
        self.trading_halted_today = False
        
        self.forming_candle_min = None
        self.forming_candle = {}
        self.last_volume = 0
        
        # Keep track of last indicators for trailing stop update on every tick
        if not self.df_1m.empty:
            from indicators.supertrend import supertrend
            st_fast = supertrend(self.df_1m, **self.cfg["indicators"]["supertrend_fast"])
            self.last_st_value = st_fast["supertrend"].iloc[-1]
            self.last_st_trend = st_fast["trend"].iloc[-1]
            from indicators.ema import calculate_ema, ema_cross_signal, ema_slope
            ind = self.cfg["indicators"]
            ema_fast = calculate_ema(self.df_1m["close"], ind["ema_fast_length"])
            ema_slow = calculate_ema(self.df_1m["close"], ind["ema_slow_length"])
            slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
            self.last_ema_signal = ema_cross_signal(
                ema_fast, ema_slow, slope_fast, self.cfg["indicators"]["ema_slope_threshold"]
            )
        else:
            self.last_st_value = 0
            self.last_st_trend = 0
            self.last_ema_signal = None

    def on_tick(self, tick: dict):
        if self.trading_halted_today:
            return

        tick_time = tick.get("timestamp")
        if not tick_time:
            tick_time = pd.Timestamp.now()
        
        tick_time = pd.Timestamp(tick_time)
        if tick_time.tz is not None:
            tick_time = tick_time.tz_localize(None)
        price = tick["last_price"]
        vol_traded = tick.get("volume_traded", 0)
        
        if self.forming_candle_min is None:
            self._start_new_candle(tick_time, price, vol_traded)
        
        current_min = tick_time.floor("1min")
        
        if current_min > self.forming_candle_min:
            # A new minute has started, close the forming candle
            self._close_candle()
            self._start_new_candle(tick_time, price, vol_traded)
            
            # Now evaluate entry/exit on closed bar
            if self.open_trade:
                self._check_closed_bar_exits(tick_time, price)
            elif not self.open_trade and self._within_trading_hours(tick_time):
                if self.trades_today < self.cfg["risk"]["max_trades_per_day"]:
                    self._check_entry()
        else:
            # Update forming candle
            self.forming_candle["high"] = max(self.forming_candle["high"], price)
            self.forming_candle["low"] = min(self.forming_candle["low"], price)
            self.forming_candle["close"] = price
            if vol_traded >= self.last_volume:
                self.forming_candle["volume"] += (vol_traded - self.last_volume)
                self.last_volume = vol_traded
        
        # Tick-level stop loss and target evaluation
        if self.open_trade:
            self._manage_tick(tick_time, price)
            
    def _start_new_candle(self, tick_time: pd.Timestamp, price: float, vol_traded: int):
        self.forming_candle_min = tick_time.floor("1min")
        self.forming_candle = {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0
        }
        self.last_volume = vol_traded

    def _close_candle(self):
        new_row = pd.DataFrame([self.forming_candle], index=[self.forming_candle_min])
        self.df_1m = pd.concat([self.df_1m, new_row])
        logger.info(f"Closed 1m candle at {self.forming_candle_min.strftime('%H:%M')} - Close: {self.forming_candle['close']}")
        
        # Re-run indicators
        self.df_5m = resample_to_5min(self.df_1m)
        
        # Update our cached indicators for tick management
        from indicators.supertrend import supertrend
        st_fast = supertrend(self.df_1m, **self.cfg["indicators"]["supertrend_fast"])
        self.last_st_value = st_fast["supertrend"].iloc[-1]
        self.last_st_trend = st_fast["trend"].iloc[-1]
        from indicators.ema import calculate_ema, ema_cross_signal, ema_slope
        ind = self.cfg["indicators"]
        ema_fast = calculate_ema(self.df_1m["close"], ind["ema_fast_length"])
        ema_slow = calculate_ema(self.df_1m["close"], ind["ema_slow_length"])
        slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
        self.last_ema_signal = ema_cross_signal(
            ema_fast, ema_slow, slope_fast, self.cfg["indicators"]["ema_slope_threshold"]
        )

    def _within_trading_hours(self, now: pd.Timestamp) -> bool:
        t = now.time()
        for start_s, end_s in self.cfg["trading_hours"]["windows"]:
            if dt_time.fromisoformat(start_s) <= t <= dt_time.fromisoformat(end_s):
                return True
        return False

    def _check_entry(self):
        # We need at least warmup_bars in 5m to generate a signal properly, 
        # but populate_indicators already ran. We just pass the DFs.
        signal = generate_signal(self.df_1m, self.df_5m, self.cfg)
        if signal.direction:
            self._enter_trade(signal)

    def _enter_trade(self, signal) -> None:
        entry_price = self.df_1m["close"].iloc[-1]
        prev_candle = self.df_1m.iloc[-2]
        from indicators.atr import calculate_atr
        atr_value = calculate_atr(self.df_1m, self.cfg["indicators"]["atr_length"]).iloc[-1]
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
            entry_time=self.df_1m.index[-1],
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
        logger.info(f"ENTERED TRADE: {signal.direction} at {entry_price} (SL: {stop_price}, TG: {target_price})")

    def _manage_tick(self, now: pd.Timestamp, price: float):
        self.open_trade.stop_price = self.tracker.update(price, self.last_st_value)

        direction = self.open_trade.direction
        hit_target = price >= self.open_trade.target_price if direction == "BUY_CALL" else price <= self.open_trade.target_price
        hit_stop = price <= self.open_trade.stop_price if direction == "BUY_CALL" else price >= self.open_trade.stop_price
        eod = now.time() >= dt_time.fromisoformat(self.cfg["trading_hours"]["square_off_time"])

        if hit_target:
            self._close_trade(now, self.open_trade.target_price, "target_hit")
        elif hit_stop:
            self._close_trade(now, self.open_trade.stop_price, "stop_hit")
        elif eod:
            self._close_trade(now, price, "eod_square_off")

    def _check_closed_bar_exits(self, now: pd.Timestamp, price: float):
        direction = self.open_trade.direction
        st_reversed = (direction == "BUY_CALL" and self.last_st_trend == -1) or (direction == "SELL_PUT" and self.last_st_trend == 1)
        ema_reversed = (direction == "BUY_CALL" and self.last_ema_signal == "bearish") or (
            direction == "SELL_PUT" and self.last_ema_signal == "bullish"
        )
        
        if st_reversed:
            self._close_trade(now, price, "supertrend_reversal")
        elif ema_reversed:
            self._close_trade(now, price, "ema_reversal")

    def _close_trade(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        self.open_trade.exit_time = exit_time
        self.open_trade.exit_price = exit_price
        self.open_trade.exit_reason = reason
        self.trades.append(self.open_trade)

        pnl = self.open_trade.pnl
        self.capital += pnl
        self.consecutive_losses = self.consecutive_losses + 1 if pnl < 0 else 0

        logger.info(f"CLOSED TRADE: {self.open_trade.direction} at {exit_price} | PnL: {pnl:.2f} | Reason: {reason}")

        daily_loss_pct = (self.day_start_capital - self.capital) / self.day_start_capital * 100
        if self.consecutive_losses >= self.cfg["risk"]["max_consecutive_losses"]:
            self.trading_halted_today = True
            logger.info("HALTED: Max consecutive losses reached.")
        if daily_loss_pct >= self.cfg["risk"]["max_daily_loss_pct"]:
            self.trading_halted_today = True
            logger.info("HALTED: Max daily loss reached.")

        self.open_trade = None
        self.tracker = None
