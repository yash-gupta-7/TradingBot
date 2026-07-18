import logging
from datetime import datetime, time as dt_time
import pandas as pd

from backtest.data_loader import resample_to_5min
from backtest.engine import Trade
from db.trades_db import get_trade_by_id, init_db, insert_trade_entry, load_daily_state, set_daily_halt, update_trade_exit
from execution.order_manager import PaperOrderManager
from risk.risk_manager import (
    TrailingStopTracker,
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
)
from strategy.strategy import generate_signal

logger = logging.getLogger(__name__)


class PaperEngine:
    def __init__(
        self,
        instrument_token: int,
        df_1m: pd.DataFrame,
        cfg: dict,
        kite=None,
        order_manager=None,
        mode: str = "paper",
        db_path: str = "db/trades.sqlite3",
        state_path: str = ".paper_state.json",
    ):
        self.instrument_token = instrument_token
        self.cfg = cfg
        self.kite = kite
        self.mode = mode
        self.order_manager = order_manager if order_manager is not None else PaperOrderManager(kite)
        self.db_path = db_path
        self.state_path = state_path
        init_db(self.db_path)
        self.open_trade_db_id: int | None = None

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
            slope_slow = ema_slope(ema_slow, ind["ema_slope_lookback"])
            self.last_ema_signal = ema_cross_signal(
                ema_fast, ema_slow, slope_fast, slope_slow, self.cfg["indicators"]["ema_slope_threshold"]
            )
        else:
            self.last_st_value = 0
            self.last_st_trend = 0
            self.last_ema_signal = None
            
        self._load_state()

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
        slope_slow = ema_slope(ema_slow, ind["ema_slope_lookback"])
        self.last_ema_signal = ema_cross_signal(
            ema_fast, ema_slow, slope_fast, slope_slow, self.cfg["indicators"]["ema_slope_threshold"]
        )

    def _within_trading_hours(self, now: pd.Timestamp) -> bool:
        t = now.time()
        for start_s, end_s in self.cfg["trading_hours"]["windows"]:
            if dt_time.fromisoformat(start_s) <= t <= dt_time.fromisoformat(end_s):
                return True
        return False

    def _check_entry(self):
        # We must only pass FULLY CLOSED 5m candles to generate_signal,
        # otherwise we evaluate against a partial/incomplete higher-timeframe bar.
        now = self.df_1m.index[-1]
        closed_5m = self.df_5m[self.df_5m.index + pd.Timedelta(minutes=5) <= now]
        
        signal = generate_signal(self.df_1m, closed_5m, self.cfg)
        if signal.direction:
            self._enter_trade(signal)

    def _resolve_atm_symbol(self, entry_price: float, direction: str) -> str | None:
        if self.kite is None:
            return None
        try:
            strike = round(entry_price / 100) * 100
            opt_type = "CE" if direction == "BUY_CALL" else "PE"

            bfo = self.kite.instruments("BFO")
            today = pd.Timestamp.now().normalize()

            options = []
            for i in bfo:
                if i["name"] == "SENSEX" and i["strike"] == strike and i["instrument_type"] == opt_type:
                    exp_date = pd.Timestamp(i["expiry"]).normalize()
                    if exp_date >= today:
                        options.append((exp_date, i["tradingsymbol"]))

            if not options:
                return None

            options.sort(key=lambda x: x[0])
            return options[0][1]
        except Exception as e:
            logger.error(f"Failed to resolve ATM option symbol: {e}")
            return None

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

        option_symbol = self._resolve_atm_symbol(entry_price, signal.direction)
        fill = self.order_manager.submit_entry(option_symbol, qty)
        if fill.status != "filled":
            logger.warning(f"Entry order for {option_symbol} was {fill.status}; skipping trade")
            return

        self.open_trade = Trade(
            entry_time=self.df_1m.index[-1],
            direction=signal.direction,
            entry_price=entry_price,
            quantity=qty,
            stop_price=stop_price,
            target_price=target_price,
            entry_reasons=signal.reasons,
            option_symbol=option_symbol,
            option_entry_price=fill.price,
        )
        self.tracker = TrailingStopTracker(
            signal.direction, entry_price, stop_price, self.cfg["risk"]["breakeven_r"], self.cfg["risk"]["trail_start_r"]
        )
        self.trades_today += 1
        self.open_trade_db_id = insert_trade_entry(
            self.db_path, self.mode, self.open_trade.entry_time.isoformat(),
            self.open_trade.direction, option_symbol, float(entry_price),
            self.open_trade.option_entry_price, qty, float(stop_price), float(target_price),
        )
        logger.info(f"ENTERED TRADE: {signal.direction} at {entry_price} (SL: {stop_price}, TG: {target_price})")
        self._save_state()

    def _manage_tick(self, now: pd.Timestamp, price: float):
        old_stop = self.open_trade.stop_price
        self.open_trade.stop_price = self.tracker.update(price, self.last_st_value)
        if self.open_trade.stop_price != old_stop:
            self._save_state()

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

    def _realized_pnl(self, trade: Trade) -> float:
        if self.mode == "live" and trade.option_entry_price is not None and trade.option_exit_price is not None:
            return (trade.option_exit_price - trade.option_entry_price) * trade.quantity
        return trade.pnl

    def _close_trade(self, exit_time: pd.Timestamp, exit_price: float, reason: str) -> None:
        exit_fill = self.order_manager.submit_exit(self.open_trade.option_symbol, self.open_trade.quantity)
        if exit_fill.status != "filled":
            logger.critical(
                f"Exit order failed for {self.open_trade.option_symbol}; leaving position open and "
                "halting trading for the day pending manual review."
            )
            self.trading_halted_today = True
            self._save_state()
            return

        self.open_trade.exit_time = exit_time
        self.open_trade.exit_price = exit_price
        self.open_trade.exit_reason = reason
        self.open_trade.option_exit_price = exit_fill.price
        self.trades.append(self.open_trade)

        pnl = self._realized_pnl(self.open_trade)
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

        if self.open_trade_db_id is not None:
            update_trade_exit(
                self.db_path, self.open_trade_db_id, exit_time.isoformat(),
                float(exit_price), self.open_trade.option_exit_price, reason, float(pnl),
            )
            self.open_trade_db_id = None

        self.open_trade = None
        self.tracker = None
        self._save_state()

    def _save_state(self):
        import json
        state = {
            "date": str(self.current_day),
            "capital": self.capital,
            "day_start_capital": self.day_start_capital,
            "trades_today": self.trades_today,
            "consecutive_losses": self.consecutive_losses,
            "trading_halted_today": self.trading_halted_today,
            "trades": [
                {
                    "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "quantity": t.quantity,
                    "stop_price": t.stop_price,
                    "target_price": t.target_price,
                    "entry_reasons": t.entry_reasons,
                    "option_symbol": t.option_symbol,
                    "option_entry_price": t.option_entry_price,
                    "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                    "exit_price": t.exit_price,
                    "exit_reason": t.exit_reason,
                } for t in self.trades
            ],
            "open_trade": None,
            "tracker": None
        }
        if self.open_trade:
            t = self.open_trade
            state["open_trade"] = {
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "quantity": t.quantity,
                "stop_price": t.stop_price,
                "target_price": t.target_price,
                "entry_reasons": t.entry_reasons,
                "option_symbol": t.option_symbol,
                "option_entry_price": t.option_entry_price,
            }
            state["tracker"] = {
                "current_stop": self.tracker.current_stop,
                "trailing_active": self.tracker.trailing_active,
                "breakeven_triggered": self.tracker.breakeven_triggered,
            }
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def _load_state(self):
        import json
        import os
        if not os.path.exists(self.state_path):
            return

        try:
            with open(self.state_path, "r") as f:
                state = json.load(f)
            
            def _dict_to_trade(d):
                return Trade(
                    entry_time=pd.Timestamp(d["entry_time"]) if d.get("entry_time") else None,
                    direction=d["direction"],
                    entry_price=d["entry_price"],
                    quantity=d["quantity"],
                    stop_price=d["stop_price"],
                    target_price=d["target_price"],
                    entry_reasons=d.get("entry_reasons", []),
                    option_symbol=d.get("option_symbol"),
                    option_entry_price=d.get("option_entry_price"),
                    exit_time=pd.Timestamp(d["exit_time"]) if d.get("exit_time") else None,
                    exit_price=d.get("exit_price"),
                    exit_reason=d.get("exit_reason"),
                )

            self.trades = [_dict_to_trade(t) for t in state.get("trades", [])]

            if state.get("date") != str(self.current_day):
                # New day! Keep account capital and trade history, but reset daily limits
                if "capital" in state:
                    self.capital = state["capital"]
                self.day_start_capital = self.capital
                self.trades_today = 0
                self.consecutive_losses = 0
                self.trading_halted_today = False
                logger.info(f"Loaded {len(self.trades)} historical trades. Starting new day with ₹{self.capital:.2f} capital.")
                return
            
            self.capital = state["capital"]
            self.day_start_capital = state["day_start_capital"]
            self.trades_today = state["trades_today"]
            self.consecutive_losses = state["consecutive_losses"]
            self.trading_halted_today = state["trading_halted_today"]
            
            if state.get("open_trade"):
                self.open_trade = _dict_to_trade(state["open_trade"])
                tr_data = state.get("tracker")
                if tr_data:
                    self.tracker = TrailingStopTracker(
                        self.open_trade.direction,
                        self.open_trade.entry_price,
                        self.open_trade.stop_price,
                        self.cfg["risk"]["breakeven_r"],
                        self.cfg["risk"]["trail_start_r"]
                    )
                    self.tracker.current_stop = tr_data["current_stop"]
                    self.tracker.trailing_active = tr_data["trailing_active"]
                    self.tracker.breakeven_triggered = tr_data["breakeven_triggered"]
            
            logger.info(f"Restored paper trading state: {len(self.trades)} trades total, {self.trades_today} trades today.")
        except Exception as e:
            logger.error(f"Failed to load paper state: {e}")

    def reconcile_live_position(self) -> None:
        """Live-mode-only startup recovery: rebuild today's halt-state
        counters from the SQLite trade log, then check the broker for a
        real open position and resume monitoring it only if it matches
        our own record. Called explicitly by run_live.py before the tick
        loop starts."""
        today = str(self.current_day)
        state = load_daily_state(
            self.db_path, self.mode, today,
            initial_capital=self.cfg["backtest"]["initial_capital"],
            max_consecutive_losses=self.cfg["risk"]["max_consecutive_losses"],
            max_daily_loss_pct=self.cfg["risk"]["max_daily_loss_pct"],
        )
        self.capital = state["capital"]
        self.day_start_capital = state["day_start_capital"]
        self.trades_today = state["trades_today"]
        self.consecutive_losses = state["consecutive_losses"]
        self.trading_halted_today = state["trading_halted_today"]
        self.open_trade_db_id = state["open_trade_id"]

        positions = self.kite.positions().get("net", [])

        if self.open_trade_db_id is None:
            self.open_trade = None
            self.tracker = None
            stray = [
                p for p in positions
                if p.get("exchange") == "BFO" and str(p.get("tradingsymbol", "")).startswith("SENSEX")
                and p.get("quantity", 0) != 0
            ]
            if stray:
                logger.critical(
                    f"Broker reports {len(stray)} open SENSEX option position(s) with no matching trade "
                    "in our log. Refusing to auto-trade until this is resolved manually."
                )
                self.trading_halted_today = True
            return

        row = get_trade_by_id(self.db_path, self.open_trade_db_id)
        broker_position = next(
            (p for p in positions if p.get("tradingsymbol") == row["option_symbol"] and p.get("quantity", 0) != 0),
            None,
        )
        if broker_position is None:
            logger.critical(
                f"SQLite has an open trade (id={self.open_trade_db_id}, symbol={row['option_symbol']}) but "
                "the broker reports no matching position. Refusing to auto-trade until this is resolved."
            )
            self.trading_halted_today = True
            self.open_trade = None
            self.tracker = None
            return

        self.open_trade = Trade(
            entry_time=pd.Timestamp(row["entry_time"]),
            direction=row["direction"],
            entry_price=row["index_entry_price"],
            quantity=row["quantity"],
            stop_price=row["stop_price"],
            target_price=row["target_price"],
            option_symbol=row["option_symbol"],
            option_entry_price=row["option_entry_price"],
        )
        self.tracker = TrailingStopTracker(
            self.open_trade.direction, self.open_trade.entry_price, self.open_trade.stop_price,
            self.cfg["risk"]["breakeven_r"], self.cfg["risk"]["trail_start_r"],
        )
        logger.info(f"Reconciled open live position: {row['option_symbol']} qty={row['quantity']}")

    def kill(self, reason: str = "manual kill switch") -> dict:
        """Immediately market-exits any open position and halts trading
        for the rest of the day. Persisted so a restart stays halted."""
        closed = False
        if self.open_trade is not None:
            exit_index_price = self.df_1m["close"].iloc[-1] if not self.df_1m.empty else self.open_trade.entry_price
            self._close_trade(pd.Timestamp.now(), exit_index_price, "kill_switch")
            closed = self.open_trade is None  # _close_trade only clears it on a confirmed exit

        self.trading_halted_today = True
        set_daily_halt(self.db_path, self.mode, str(self.current_day), True, reason)
        self._save_state()
        return {"closed_position": closed, "halted": True}
