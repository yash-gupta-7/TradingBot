import pandas as pd
import pytest

from live.paper_engine import PaperEngine
from strategy.strategy import Signal
from execution.order_manager import Fill

CFG = {
    "instrument": {"lot_size": 20},
    "indicators": {
        "supertrend_fast": {"length": 10, "multiplier": 1},
        "supertrend_slow": {"length": 10, "multiplier": 3},
        "ema_fast_length": 9,
        "ema_slow_length": 15,
        "ema_slope_lookback": 3,
        "ema_slope_threshold": 0.01,
        "rsi_length": 14,
        "rsi_midline": 50,
        "adx_length": 14,
        "adx_threshold": 25,
        "atr_length": 14,
        "atr_sma_length": 14,
        "volume_lookback": 20,
        "volume_multiplier": 1.5,
    },
    "risk": {
        "risk_pct": 1.0,
        "reward_risk_ratio": 2.0,
        "atr_stop_multiplier": 1.5,
        "breakeven_r": 1.0,
        "trail_start_r": 1.5,
        "max_trades_per_day": 5,
        "max_consecutive_losses": 3,
        "max_daily_loss_pct": 2.0,
    },
    "trading_hours": {"windows": [["09:15", "15:30"]], "square_off_time": "15:20"},
    "backtest": {"initial_capital": 100000, "warmup_bars": 60},
}


def _flat_df(n=30):
    idx = pd.date_range("2026-07-18 09:15", periods=n, freq="1min")
    return pd.DataFrame({
        "open": [75000.0] * n,
        "high": [75010.0] * n,
        "low": [74990.0] * n,
        "close": [75000.0] * n,
        "volume": [1000] * n,
    }, index=idx)


class _StubOrderManager:
    def __init__(self, entry_price=150.0, exit_price=200.0):
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.entry_calls = []
        self.exit_calls = []

    def submit_entry(self, option_symbol, quantity):
        self.entry_calls.append((option_symbol, quantity))
        return Fill(status="filled", price=self.entry_price, order_id="E1")

    def submit_exit(self, option_symbol, quantity):
        self.exit_calls.append((option_symbol, quantity))
        return Fill(status="filled", price=self.exit_price, order_id="X1")


def _make_engine(tmp_path, order_manager=None, mode="paper"):
    return PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=None,
        order_manager=order_manager, mode=mode,
        db_path=str(tmp_path / "trades.sqlite3"),
        state_path=str(tmp_path / "paper_state.json"),
    )


def test_enter_trade_uses_order_manager_fill_price(tmp_path):
    om = _StubOrderManager(entry_price=155.5)
    engine = _make_engine(tmp_path, order_manager=om)

    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))

    assert engine.open_trade is not None
    assert engine.open_trade.option_entry_price == 155.5
    assert om.entry_calls == [(None, engine.open_trade.quantity)]
    assert engine.open_trade_db_id is not None


def test_enter_trade_skipped_when_order_rejected(tmp_path):
    class _RejectingOrderManager:
        def submit_entry(self, option_symbol, quantity):
            return Fill(status="rejected", price=None, order_id=None)

        def submit_exit(self, option_symbol, quantity):
            raise AssertionError("should not be called")

    engine = _make_engine(tmp_path, order_manager=_RejectingOrderManager())
    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))

    assert engine.open_trade is None
    assert engine.trades_today == 0


def test_close_trade_live_mode_pnl_uses_option_fill_prices(tmp_path):
    om = _StubOrderManager(entry_price=150.0, exit_price=250.0)
    engine = _make_engine(tmp_path, order_manager=om, mode="live")
    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))
    qty = engine.open_trade.quantity

    engine._close_trade(pd.Timestamp("2026-07-18 09:45"), 75150.0, "target_hit")

    expected_pnl = (250.0 - 150.0) * qty
    assert engine.capital == pytest.approx(100000.0 + expected_pnl)
    assert engine.open_trade is None
    assert om.exit_calls[-1][1] == qty


def test_close_trade_paper_mode_pnl_uses_index_prices(tmp_path):
    om = _StubOrderManager(entry_price=150.0, exit_price=250.0)
    engine = _make_engine(tmp_path, order_manager=om, mode="paper")
    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))
    qty = engine.open_trade.quantity
    entry_index_price = engine.open_trade.entry_price

    engine._close_trade(pd.Timestamp("2026-07-18 09:45"), 75150.0, "target_hit")

    expected_pnl = (75150.0 - entry_index_price) * qty
    assert engine.capital == pytest.approx(100000.0 + expected_pnl)


def test_close_trade_leaves_position_open_when_exit_order_fails(tmp_path):
    class _FailingExitOrderManager(_StubOrderManager):
        def submit_exit(self, option_symbol, quantity):
            self.exit_calls.append((option_symbol, quantity))
            return Fill(status="rejected", price=None, order_id=None)

    om = _FailingExitOrderManager()
    engine = _make_engine(tmp_path, order_manager=om, mode="live")
    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))
    assert engine.open_trade is not None

    engine._close_trade(pd.Timestamp("2026-07-18 09:45"), 75150.0, "target_hit")

    assert engine.open_trade is not None  # still open — exit not confirmed
    assert engine.trading_halted_today is True


from db.trades_db import init_db as _init_db, insert_trade_entry as _insert_trade_entry


class _FakeKitePositions:
    def __init__(self, net):
        self._net = net

    def positions(self):
        return {"net": self._net}


def test_reconcile_resumes_matching_open_position(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    _init_db(db_path)
    trade_id = _insert_trade_entry(
        db_path, "live", "2026-07-18T09:30:00", "BUY_CALL", "SENSEX2572575000CE",
        75000.0, 150.0, 20, 74900.0, 75150.0,
    )
    kite = _FakeKitePositions([{"tradingsymbol": "SENSEX2572575000CE", "exchange": "BFO", "quantity": 20}])
    engine = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=kite,
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state.json"),
    )
    engine.current_day = pd.Timestamp("2026-07-18").date()

    engine.reconcile_live_position()

    assert engine.open_trade is not None
    assert engine.open_trade.option_symbol == "SENSEX2572575000CE"
    assert engine.open_trade_db_id == trade_id
    assert engine.tracker is not None
    assert engine.trading_halted_today is False


def test_reconcile_halts_when_broker_position_unmatched(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    _init_db(db_path)
    _insert_trade_entry(
        db_path, "live", "2026-07-18T09:30:00", "BUY_CALL", "SENSEX2572575000CE",
        75000.0, 150.0, 20, 74900.0, 75150.0,
    )
    kite = _FakeKitePositions([])  # broker shows nothing
    engine = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=kite,
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state.json"),
    )
    engine.current_day = pd.Timestamp("2026-07-18").date()

    engine.reconcile_live_position()

    assert engine.trading_halted_today is True
    assert engine.open_trade is None


def test_reconcile_halts_on_stray_broker_position(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    _init_db(db_path)
    kite = _FakeKitePositions([{"tradingsymbol": "SENSEX2572575000PE", "exchange": "BFO", "quantity": 20}])
    engine = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=kite,
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state.json"),
    )
    engine.current_day = pd.Timestamp("2026-07-18").date()

    engine.reconcile_live_position()

    assert engine.trading_halted_today is True
    assert engine.open_trade is None


def test_reconcile_cold_start_is_noop(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    _init_db(db_path)
    kite = _FakeKitePositions([])
    engine = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=kite,
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state.json"),
    )
    engine.current_day = pd.Timestamp("2026-07-18").date()

    engine.reconcile_live_position()

    assert engine.open_trade is None
    assert engine.trading_halted_today is False
