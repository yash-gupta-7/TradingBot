"""SQLite trade log, shared by paper and live PaperEngine instances.

Live mode uses this as the source of truth for rebuilding daily
halt-state after a restart (see load_daily_state in the next task) —
paper mode keeps using .paper_state.json for that, this table is just
a bonus queryable trade history for it.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

_TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    direction TEXT NOT NULL,
    option_symbol TEXT,
    index_entry_price REAL NOT NULL,
    index_exit_price REAL,
    option_entry_price REAL,
    option_exit_price REAL,
    quantity INTEGER NOT NULL,
    stop_price REAL NOT NULL,
    target_price REAL NOT NULL,
    exit_reason TEXT,
    pnl REAL
)
"""

_HALT_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_halt (
    date TEXT NOT NULL,
    mode TEXT NOT NULL,
    halted INTEGER NOT NULL,
    reason TEXT,
    PRIMARY KEY (date, mode)
)
"""


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(_TRADES_SCHEMA)
        conn.execute(_HALT_SCHEMA)
        conn.commit()


def insert_trade_entry(
    db_path: str,
    mode: str,
    entry_time: str,
    direction: str,
    option_symbol: str | None,
    index_entry_price: float,
    option_entry_price: float | None,
    quantity: int,
    stop_price: float,
    target_price: float,
) -> int:
    with closing(sqlite3.connect(db_path)) as conn:
        cur = conn.execute(
            """INSERT INTO trades
               (mode, entry_time, direction, option_symbol, index_entry_price,
                option_entry_price, quantity, stop_price, target_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mode, entry_time, direction, option_symbol, index_entry_price,
             option_entry_price, quantity, stop_price, target_price),
        )
        conn.commit()
        return cur.lastrowid


def update_trade_exit(
    db_path: str,
    trade_id: int,
    exit_time: str,
    index_exit_price: float,
    option_exit_price: float | None,
    exit_reason: str,
    pnl: float,
) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """UPDATE trades
               SET exit_time = ?, index_exit_price = ?, option_exit_price = ?,
                   exit_reason = ?, pnl = ?
               WHERE id = ?""",
            (exit_time, index_exit_price, option_exit_price, exit_reason, pnl, trade_id),
        )
        conn.commit()
