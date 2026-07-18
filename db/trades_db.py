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


def load_daily_state(
    db_path: str,
    mode: str,
    day: str,
    initial_capital: float,
    max_consecutive_losses: int,
    max_daily_loss_pct: float,
) -> dict:
    """Rebuild today's risk-halt counters by replaying the trade log —
    the mechanism that lets live mode survive a restart without losing
    track of daily loss limits."""
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        prior_pnl = conn.execute(
            """SELECT COALESCE(SUM(pnl), 0) AS total FROM trades
               WHERE mode = ? AND pnl IS NOT NULL AND date(entry_time) < date(?)""",
            (mode, day),
        ).fetchone()["total"]
        day_start_capital = initial_capital + prior_pnl

        today_rows = conn.execute(
            """SELECT * FROM trades WHERE mode = ? AND date(entry_time) = date(?)
               ORDER BY entry_time ASC""",
            (mode, day),
        ).fetchall()

        capital = day_start_capital
        consecutive_losses = 0
        open_trade_id = None
        threshold_halt = False
        for row in today_rows:
            if row["pnl"] is None:
                open_trade_id = row["id"]
                continue
            capital += row["pnl"]
            consecutive_losses = consecutive_losses + 1 if row["pnl"] < 0 else 0
            if consecutive_losses >= max_consecutive_losses:
                threshold_halt = True
            daily_loss_pct = (day_start_capital - capital) / day_start_capital * 100 if day_start_capital else 0
            if daily_loss_pct >= max_daily_loss_pct:
                threshold_halt = True

        halt_row = conn.execute(
            "SELECT halted FROM daily_halt WHERE date = ? AND mode = ?", (day, mode)
        ).fetchone()
        manual_halt = bool(halt_row["halted"]) if halt_row else False

        return {
            "capital": capital,
            "day_start_capital": day_start_capital,
            "trades_today": len(today_rows),
            "consecutive_losses": consecutive_losses,
            "trading_halted_today": manual_halt or threshold_halt,
            "open_trade_id": open_trade_id,
        }


def set_daily_halt(db_path: str, mode: str, day: str, halted: bool, reason: str) -> None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """INSERT INTO daily_halt (date, mode, halted, reason) VALUES (?, ?, ?, ?)
               ON CONFLICT(date, mode) DO UPDATE SET halted = excluded.halted, reason = excluded.reason""",
            (day, mode, int(halted), reason),
        )
        conn.commit()


def get_trade_by_id(db_path: str, trade_id: int) -> dict | None:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return dict(row) if row else None
