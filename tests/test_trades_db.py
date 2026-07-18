import sqlite3

from db.trades_db import init_db, insert_trade_entry, update_trade_exit, load_daily_state, set_daily_halt, get_trade_by_id


def test_insert_and_update_round_trip(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)

    trade_id = insert_trade_entry(
        db_path, mode="live", entry_time="2026-07-18T09:30:00",
        direction="BUY_CALL", option_symbol="SENSEX2572575000CE",
        index_entry_price=75000.0, option_entry_price=150.0,
        quantity=20, stop_price=74900.0, target_price=75150.0,
    )
    assert trade_id == 1

    update_trade_exit(
        db_path, trade_id, exit_time="2026-07-18T10:00:00",
        index_exit_price=75150.0, option_exit_price=200.0,
        exit_reason="target_hit", pnl=1000.0,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()

    assert row["exit_reason"] == "target_hit"
    assert row["pnl"] == 1000.0
    assert row["option_exit_price"] == 200.0
    assert row["mode"] == "live"


def test_open_trade_has_null_exit_fields(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    trade_id = insert_trade_entry(
        db_path, "paper", "2026-07-18T09:30:00", "BUY_CALL", "SYM1",
        75000.0, 150.0, 20, 74900.0, 75150.0,
    )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
    conn.close()

    assert row["exit_time"] is None
    assert row["pnl"] is None


def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    init_db(db_path)  # must not raise


def test_load_daily_state_rebuilds_halt_after_two_consecutive_losses(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    day = "2026-07-18"
    t1 = insert_trade_entry(db_path, "live", f"{day}T09:30:00", "BUY_CALL", "SYM1", 75000, 150, 20, 74900, 75150)
    update_trade_exit(db_path, t1, f"{day}T09:45:00", 74900, 100, "stop_hit", -1000.0)
    t2 = insert_trade_entry(db_path, "live", f"{day}T10:00:00", "BUY_CALL", "SYM2", 75100, 150, 20, 75000, 75250)
    update_trade_exit(db_path, t2, f"{day}T10:15:00", 75000, 100, "stop_hit", -1000.0)

    state = load_daily_state(db_path, "live", day, initial_capital=10000,
                              max_consecutive_losses=2, max_daily_loss_pct=50.0)

    assert state["trades_today"] == 2
    assert state["consecutive_losses"] == 2
    assert state["trading_halted_today"] is True
    assert state["capital"] == 8000.0
    assert state["day_start_capital"] == 10000.0
    assert state["open_trade_id"] is None


def test_load_daily_state_tracks_open_trade(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    day = "2026-07-18"
    t1 = insert_trade_entry(db_path, "live", f"{day}T09:30:00", "BUY_CALL", "SYM1", 75000, 150, 20, 74900, 75150)

    state = load_daily_state(db_path, "live", day, initial_capital=10000,
                              max_consecutive_losses=3, max_daily_loss_pct=35.0)

    assert state["open_trade_id"] == t1
    assert state["trading_halted_today"] is False


def test_load_daily_state_ignores_other_modes_and_days(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    t1 = insert_trade_entry(db_path, "paper", "2026-07-18T09:30:00", "BUY_CALL", "SYM1", 75000, 150, 20, 74900, 75150)
    update_trade_exit(db_path, t1, "2026-07-18T09:45:00", 75150, 200, "target_hit", 1000.0)
    t2 = insert_trade_entry(db_path, "live", "2026-07-17T09:30:00", "BUY_CALL", "SYM2", 75000, 150, 20, 74900, 75150)
    update_trade_exit(db_path, t2, "2026-07-17T09:45:00", 74900, 100, "stop_hit", -500.0)

    state = load_daily_state(db_path, "live", "2026-07-18", initial_capital=10000,
                              max_consecutive_losses=3, max_daily_loss_pct=35.0)

    assert state["trades_today"] == 0
    assert state["day_start_capital"] == 9500.0
    assert state["capital"] == 9500.0


def test_set_daily_halt_persists_manual_halt(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    set_daily_halt(db_path, "live", "2026-07-18", True, "manual kill switch")

    state = load_daily_state(db_path, "live", "2026-07-18", initial_capital=10000,
                              max_consecutive_losses=3, max_daily_loss_pct=35.0)

    assert state["trading_halted_today"] is True


def test_set_daily_halt_upsert_overwrites(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    set_daily_halt(db_path, "live", "2026-07-18", True, "manual")
    set_daily_halt(db_path, "live", "2026-07-18", False, "resumed")

    state = load_daily_state(db_path, "live", "2026-07-18", initial_capital=10000,
                              max_consecutive_losses=3, max_daily_loss_pct=35.0)

    assert state["trading_halted_today"] is False


def test_get_trade_by_id_returns_row_as_dict(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    trade_id = insert_trade_entry(db_path, "live", "2026-07-18T09:30:00", "BUY_CALL", "SYM1", 75000, 150, 20, 74900, 75150)

    row = get_trade_by_id(db_path, trade_id)

    assert row["option_symbol"] == "SYM1"
    assert row["direction"] == "BUY_CALL"
    assert row["exit_time"] is None


def test_get_trade_by_id_missing_returns_none(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    init_db(db_path)
    assert get_trade_by_id(db_path, 999) is None
