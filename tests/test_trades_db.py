import sqlite3

from db.trades_db import init_db, insert_trade_entry, update_trade_exit


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
