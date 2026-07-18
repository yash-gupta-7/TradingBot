# Phase 2 — Live Order Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real Kite order placement to the existing live paper-trading engine, without changing how entries/exits are decided, gated behind explicit multi-layer opt-ins since this places real money on the line.

**Architecture:** A new `execution/order_manager.py` defines an `OrderManager` interface (`submit_entry`/`submit_exit` → `Fill`) with two implementations: `PaperOrderManager` (today's simulated-fill behavior, extracted unchanged) and `LiveOrderManager` (real `kite.place_order` + status polling). `PaperEngine` (in `live/paper_engine.py`) is extended to accept an injected `order_manager` and a `mode` ("paper"/"live") — its entry/exit *decision* logic (index price, indicators, stop/target/trailing) is untouched; only the fill step is delegated. A new `db/trades_db.py` (SQLite, stdlib) logs every trade for both modes and is live mode's source of truth for rebuilding daily halt-state after a restart, superseding `.paper_state.json` for that purpose. `live/run_live.py` is a new CLI entrypoint enforcing three independent safety gates before any real order can be placed, plus startup reconciliation against the broker's actual positions.

**Tech Stack:** Python 3.12, `kiteconnect` (`place_order`, `order_history`, `positions`), `sqlite3` (stdlib, no new dependency), pytest.

**Design doc:** `docs/superpowers/specs/2026-07-18-phase2-live-order-execution-design.md`

## Global Constraints

- Paper mode is the default everywhere; live mode requires ALL of: `--live` CLI flag on `run_live.py`, `config.yaml` `execution.mode: live`, and `execution.confirm_live: true`. Missing any one refuses to start.
- `strategy/strategy.py`, `risk/risk_manager.py`, and all of `backtest/` are out of scope — entries/exits are still decided purely from index price and indicators, exactly as today.
- Every real order is a BUY to open (CE or PE, per the existing `BUY_CALL`/`SELL_PUT` → `CE`/`PE` mapping) and a SELL to close — the bot never sells to open.
- A rejected or timed-out **exit** order must never be treated as a closed position — `PaperEngine` must leave `open_trade` set and halt trading rather than silently losing track of a real position.
- `db/trades_db.py` (SQLite) is live mode's source of truth for rebuilding `trades_today`/`consecutive_losses`/`day_start_capital`/`trading_halted_today` after a restart. `.paper_state.json` remains paper mode's existing, unmodified mechanism.
- No new third-party dependency — `sqlite3` is in the Python standard library.

---

## File Structure

```
TradingBot/
├── execution/                       # NEW package
│   ├── __init__.py                   # NEW, empty
│   └── order_manager.py              # NEW: Fill, PaperOrderManager, LiveOrderManager
├── db/                                # NEW package
│   ├── __init__.py                   # NEW, empty
│   └── trades_db.py                  # NEW: SQLite schema + read/write helpers
├── backtest/
│   └── engine.py                     # MODIFY: Trade gains option_exit_price field
├── live/
│   ├── paper_engine.py               # MODIFY: order_manager/mode/db wiring, reconciliation, kill()
│   ├── api.py                        # MODIFY: add POST /api/kill
│   ├── run_paper.py                  # MODIFY: delegate ws loop to ticker_loop.py
│   ├── ticker_loop.py                # NEW: shared websocket reconnect loop
│   ├── run_live.py                   # NEW: live-mode CLI entrypoint with safety gates
│   └── kill_switch.py                # NEW: CLI kill switch client
├── config/
│   └── config.yaml                   # MODIFY: add `execution.mode` / `execution.confirm_live`
├── .gitignore                        # MODIFY: ignore *.sqlite3
├── README.md                         # MODIFY: Phase 2 section + pre-flight checklist
└── tests/
    ├── test_order_manager.py         # NEW
    ├── test_trades_db.py             # NEW
    ├── test_paper_engine.py          # NEW (first test coverage for this file)
    ├── test_ticker_loop.py           # NEW
    ├── test_run_live_safety_gates.py # NEW
    └── test_kill_switch_api.py       # NEW
```

---

### Task 1: `Fill` + `PaperOrderManager`

**Files:**
- Create: `execution/__init__.py` (empty)
- Create: `execution/order_manager.py`
- Test: `tests/test_order_manager.py`

**Interfaces:**
- Produces: `Fill(status: str, price: float | None, order_id: str | None = None)` — `status` is `"filled"` or `"rejected"`. `PaperOrderManager(kite=None)` with `.submit_entry(option_symbol: str | None, quantity: int) -> Fill` and `.submit_exit(option_symbol: str | None, quantity: int) -> Fill`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_order_manager.py`:

```python
from execution.order_manager import Fill, PaperOrderManager


class _FakeKite:
    def __init__(self, price):
        self.price = price

    def quote(self, symbols):
        return {symbols[0]: {"last_price": self.price}}


def test_paper_entry_fills_at_quote_price():
    om = PaperOrderManager(kite=_FakeKite(123.45))
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill == Fill(status="filled", price=123.45, order_id=None)


def test_paper_exit_fills_at_quote_price():
    om = PaperOrderManager(kite=_FakeKite(98.7))
    fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price == 98.7


def test_paper_entry_with_no_kite_fills_with_none_price():
    om = PaperOrderManager(kite=None)
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price is None


def test_paper_entry_with_no_symbol_fills_with_none_price():
    om = PaperOrderManager(kite=_FakeKite(123.45))
    fill = om.submit_entry(None, 20)
    assert fill.status == "filled"
    assert fill.price is None


def test_paper_entry_quote_failure_fills_with_none_price():
    class _BrokenKite:
        def quote(self, symbols):
            raise RuntimeError("network error")

    om = PaperOrderManager(kite=_BrokenKite())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'execution'`

- [ ] **Step 3: Write the implementation**

Create `execution/__init__.py` (empty file).

Create `execution/order_manager.py`:

```python
"""Order execution abstraction: paper (simulated) vs live (real Kite orders).

PaperEngine decides *when* to enter/exit purely from index price and
indicators (unchanged). An OrderManager only decides *how a decided trade
becomes a fill* — this is the only thing that differs between paper and
live trading.
"""
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    status: str  # "filled" or "rejected"
    price: float | None
    order_id: str | None = None


class PaperOrderManager:
    """Simulates an instant fill at the current market quote. Never
    rejects a trade — a quote lookup failure just means the trade
    proceeds with a None option price (paper P&L is priced off the
    index, not the option premium, so this has no financial effect)."""

    def __init__(self, kite=None):
        self.kite = kite

    def _quote_price(self, option_symbol: str | None) -> float | None:
        if self.kite is None or option_symbol is None:
            return None
        try:
            quote = self.kite.quote([f"BFO:{option_symbol}"])
            return quote.get(f"BFO:{option_symbol}", {}).get("last_price")
        except Exception as e:
            logger.error(f"Failed to fetch quote for {option_symbol}: {e}")
            return None

    def submit_entry(self, option_symbol: str | None, quantity: int) -> Fill:
        return Fill(status="filled", price=self._quote_price(option_symbol), order_id=None)

    def submit_exit(self, option_symbol: str | None, quantity: int) -> Fill:
        return Fill(status="filled", price=self._quote_price(option_symbol), order_id=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_manager.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add execution/__init__.py execution/order_manager.py tests/test_order_manager.py
git commit -m "feat: PaperOrderManager order execution abstraction"
```

---

### Task 2: `LiveOrderManager`

**Files:**
- Modify: `execution/order_manager.py`
- Test: `tests/test_order_manager.py`

**Interfaces:**
- Consumes: `Fill` from Task 1.
- Produces: `LiveOrderManager(kite)` with the same `.submit_entry`/`.submit_exit` interface as `PaperOrderManager`, so `PaperEngine` (Task 5) can use either interchangeably.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_order_manager.py`:

```python
from execution.order_manager import LiveOrderManager


class _FakeKiteFilled:
    def __init__(self):
        self.placed = []

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        return "order123"

    def order_history(self, order_id):
        return [{"status": "OPEN"}, {"status": "COMPLETE", "average_price": 145.5}]


def test_live_entry_fills_on_complete(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteFilled())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill == Fill(status="filled", price=145.5, order_id="order123")


def test_live_entry_places_a_buy_market_order(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    kite = _FakeKiteFilled()
    om = LiveOrderManager(kite=kite)
    om.submit_entry("SENSEX2572575000CE", 20)
    assert kite.placed[0]["transaction_type"] == "BUY"
    assert kite.placed[0]["quantity"] == 20
    assert kite.placed[0]["order_type"] == "MARKET"
    assert kite.placed[0]["exchange"] == "BFO"
    assert kite.placed[0]["tradingsymbol"] == "SENSEX2572575000CE"


def test_live_exit_places_a_sell_market_order(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    kite = _FakeKiteFilled()
    om = LiveOrderManager(kite=kite)
    om.submit_exit("SENSEX2572575000CE", 20)
    assert kite.placed[0]["transaction_type"] == "SELL"


class _FakeKiteRejected:
    def place_order(self, **kwargs):
        return "order999"

    def order_history(self, order_id):
        return [{"status": "REJECTED"}]


def test_live_entry_rejected_returns_rejected_fill(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteRejected())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"
    assert fill.price is None


class _FakeKiteNeverTerminal:
    def place_order(self, **kwargs):
        return "order555"

    def order_history(self, order_id):
        return [{"status": "OPEN"}]


def test_live_entry_timeout_returns_rejected_fill(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)
    om = LiveOrderManager(kite=_FakeKiteNeverTerminal())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"


def test_live_entry_place_order_exception_returns_rejected_fill(monkeypatch):
    class _FakeKiteThrows:
        def place_order(self, **kwargs):
            raise RuntimeError("network down")

    om = LiveOrderManager(kite=_FakeKiteThrows())
    fill = om.submit_entry("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"


def test_live_entry_with_no_symbol_is_rejected_without_placing_order():
    class _KiteShouldNotBeCalled:
        def place_order(self, **kwargs):
            raise AssertionError("should not place an order with no resolved symbol")

    om = LiveOrderManager(kite=_KiteShouldNotBeCalled())
    fill = om.submit_entry(None, 20)
    assert fill.status == "rejected"


def test_live_exit_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)

    class _FlakyKite:
        def __init__(self):
            self.calls = 0

        def place_order(self, **kwargs):
            self.calls += 1
            return f"order{self.calls}"

        def order_history(self, order_id):
            if order_id == "order1":
                return [{"status": "REJECTED"}]
            return [{"status": "COMPLETE", "average_price": 100.0}]

    om = LiveOrderManager(kite=_FlakyKite())
    fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "filled"
    assert fill.price == 100.0


def test_live_exit_exhausts_retries_and_logs_critical(monkeypatch, caplog):
    import logging
    monkeypatch.setattr("execution.order_manager.time.sleep", lambda s: None)

    om = LiveOrderManager(kite=_FakeKiteRejected())
    with caplog.at_level(logging.CRITICAL, logger="execution.order_manager"):
        fill = om.submit_exit("SENSEX2572575000CE", 20)
    assert fill.status == "rejected"
    assert any("Manual intervention required" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_order_manager.py -v`
Expected: FAIL with `ImportError: cannot import name 'LiveOrderManager'`

- [ ] **Step 3: Write the implementation**

Append to `execution/order_manager.py`:

```python
class LiveOrderManager:
    """Places real Kite orders and polls for a terminal fill status.

    A rejected/timed-out *entry* just means no trade happened. A
    rejected/timed-out *exit* is the dangerous case (a real open
    position the bot can no longer confirm is closed) — it retries the
    SELL a bounded number of times before giving up loudly.
    """

    POLL_INTERVALS = (1, 2, 3, 4, 5)  # seconds between polls, ~15s total
    EXIT_RETRY_ATTEMPTS = 3

    def __init__(self, kite):
        self.kite = kite

    def _place_and_wait(self, transaction_type: str, option_symbol: str, quantity: int) -> Fill:
        try:
            order_id = self.kite.place_order(
                variety="regular",
                exchange="BFO",
                tradingsymbol=option_symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                order_type="MARKET",
                product="MIS",
            )
        except Exception as e:
            logger.error(f"place_order failed for {option_symbol}: {e}")
            return Fill(status="rejected", price=None, order_id=None)

        for wait_s in self.POLL_INTERVALS:
            time.sleep(wait_s)
            try:
                history = self.kite.order_history(order_id)
            except Exception as e:
                logger.error(f"order_history failed for {order_id}: {e}")
                continue
            last = history[-1] if history else {}
            status = last.get("status")
            if status == "COMPLETE":
                return Fill(status="filled", price=last.get("average_price"), order_id=order_id)
            if status in ("REJECTED", "CANCELLED"):
                logger.error(f"Order {order_id} for {option_symbol} ended in {status}")
                return Fill(status="rejected", price=None, order_id=order_id)

        logger.error(f"Order {order_id} for {option_symbol} did not reach a terminal status in time")
        return Fill(status="rejected", price=None, order_id=order_id)

    def submit_entry(self, option_symbol: str | None, quantity: int) -> Fill:
        if option_symbol is None:
            logger.error("Cannot place a live entry order with no resolved option contract")
            return Fill(status="rejected", price=None, order_id=None)
        return self._place_and_wait("BUY", option_symbol, quantity)

    def submit_exit(self, option_symbol: str | None, quantity: int) -> Fill:
        if option_symbol is None:
            logger.critical("Cannot place a live exit order with no resolved option contract — position is untracked!")
            return Fill(status="rejected", price=None, order_id=None)
        for attempt in range(1, self.EXIT_RETRY_ATTEMPTS + 1):
            fill = self._place_and_wait("SELL", option_symbol, quantity)
            if fill.status == "filled":
                return fill
            logger.error(f"Exit attempt {attempt}/{self.EXIT_RETRY_ATTEMPTS} failed for {option_symbol}")
        logger.critical(
            f"EXIT FAILED after {self.EXIT_RETRY_ATTEMPTS} attempts for {option_symbol} qty={quantity} — "
            "a real position may still be open. Manual intervention required."
        )
        return Fill(status="rejected", price=None, order_id=None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_order_manager.py -v`
Expected: PASS (13 tests total)

- [ ] **Step 5: Commit**

```bash
git add execution/order_manager.py tests/test_order_manager.py
git commit -m "feat: LiveOrderManager for real Kite order placement"
```

---

### Task 3: `db/trades_db.py` — schema, insert, update

**Files:**
- Create: `db/__init__.py` (empty)
- Create: `db/trades_db.py`
- Test: `tests/test_trades_db.py`

**Interfaces:**
- Produces: `init_db(db_path: str) -> None`, `insert_trade_entry(db_path, mode, entry_time, direction, option_symbol, index_entry_price, option_entry_price, quantity, stop_price, target_price) -> int` (returns row id), `update_trade_exit(db_path, trade_id, exit_time, index_exit_price, option_exit_price, exit_reason, pnl) -> None`. All time args are ISO strings.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_trades_db.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trades_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Write the implementation**

Create `db/__init__.py` (empty file).

Create `db/trades_db.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trades_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add db/__init__.py db/trades_db.py tests/test_trades_db.py
git commit -m "feat: SQLite trade log schema and insert/update helpers"
```

---

### Task 4: `db/trades_db.py` — daily halt-state rebuild

**Files:**
- Modify: `db/trades_db.py`
- Test: `tests/test_trades_db.py`

**Interfaces:**
- Consumes: the `trades` table from Task 3.
- Produces: `load_daily_state(db_path, mode, day, initial_capital, max_consecutive_losses, max_daily_loss_pct) -> dict` with keys `capital`, `day_start_capital`, `trades_today`, `consecutive_losses`, `trading_halted_today`, `open_trade_id`. `set_daily_halt(db_path, mode, day, halted, reason) -> None`. `get_trade_by_id(db_path, trade_id) -> dict | None`. `day` is an ISO date string (`YYYY-MM-DD`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trades_db.py`:

```python
from db.trades_db import load_daily_state, set_daily_halt, get_trade_by_id


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trades_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_daily_state'`

- [ ] **Step 3: Write the implementation**

Append to `db/trades_db.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trades_db.py -v`
Expected: PASS (10 tests total)

- [ ] **Step 5: Commit**

```bash
git add db/trades_db.py tests/test_trades_db.py
git commit -m "feat: rebuild daily halt-state from the trade log for restart recovery"
```

---

### Task 5: Wire `PaperEngine` to `OrderManager` + SQLite logging

**Files:**
- Modify: `backtest/engine.py:23-42` (`Trade` dataclass)
- Modify: `live/paper_engine.py`
- Test: `tests/test_paper_engine.py` (new file — `PaperEngine` currently has no test coverage)

**Interfaces:**
- Consumes: `Fill`, `PaperOrderManager` (Task 1), `insert_trade_entry`, `update_trade_exit`, `init_db` (Task 3).
- Produces: `PaperEngine(instrument_token, df_1m, cfg, kite=None, order_manager=None, mode="paper", db_path="db/trades.sqlite3", state_path=".paper_state.json")`. `Trade` gains `option_exit_price: float | None = None`.

- [ ] **Step 1: Add `option_exit_price` to `Trade`**

In `backtest/engine.py`, the `Trade` dataclass currently ends:

```python
    option_symbol: str | None = None
    option_entry_price: float | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
```

Change to:

```python
    option_symbol: str | None = None
    option_entry_price: float | None = None
    option_exit_price: float | None = None
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
```

- [ ] **Step 2: Run existing backtest tests to confirm the field addition is non-breaking**

Run: `pytest tests/test_engine.py tests/test_metrics.py -v`
Expected: PASS (unchanged — the new field has a default and nothing reads it yet)

- [ ] **Step 3: Write the failing tests**

Create `tests/test_paper_engine.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/test_paper_engine.py -v`
Expected: FAIL — `PaperEngine.__init__()` doesn't accept `order_manager`/`mode`/`db_path`/`state_path` yet

- [ ] **Step 5: Write the implementation**

In `live/paper_engine.py`, update the imports at the top:

```python
import logging
from datetime import datetime, time as dt_time
import pandas as pd

from backtest.data_loader import resample_to_5min
from backtest.engine import Trade
from db.trades_db import init_db, insert_trade_entry, update_trade_exit
from execution.order_manager import PaperOrderManager
from risk.risk_manager import (
    TrailingStopTracker,
    calculate_position_size,
    calculate_stop_loss,
    calculate_target,
)
from strategy.strategy import generate_signal

logger = logging.getLogger(__name__)
```

Replace the `__init__` signature and its first lines:

```python
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
```

(keep everything else in `__init__` unchanged — `df_1m`/`df_5m`/`capital`/`trades`/etc. are untouched).

Replace `_get_atm_option` with `_resolve_atm_symbol` (contract lookup only — no quote fetch, that's the order manager's job now):

```python
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
```

Replace `_enter_trade`:

```python
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
```

Add a `_realized_pnl` helper and replace `_close_trade`:

```python
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
```

Finally, in `_save_state` and `_load_state`, replace both hardcoded occurrences of `".paper_state.json"` with `self.state_path`:

```python
        with open(self.state_path, "w") as f:
            json.dump(state, f)
```

```python
        if not os.path.exists(self.state_path):
            return
        ...
            with open(self.state_path, "r") as f:
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_paper_engine.py tests/test_engine.py tests/test_metrics.py -v`
Expected: PASS (all)

- [ ] **Step 7: Run the full suite for a regression check**

Run: `pytest -v`
Expected: PASS (no existing test touches `PaperEngine`'s old `_get_atm_option` signature or the JSON state file path directly, so nothing else should break)

- [ ] **Step 8: Commit**

```bash
git add backtest/engine.py live/paper_engine.py tests/test_paper_engine.py
git commit -m "feat: wire PaperEngine entries/exits through OrderManager + SQLite log"
```

---

### Task 6: Startup reconciliation against the broker

**Files:**
- Modify: `live/paper_engine.py`
- Test: `tests/test_paper_engine.py`

**Interfaces:**
- Consumes: `load_daily_state`, `get_trade_by_id` (Task 4).
- Produces: `PaperEngine.reconcile_live_position() -> None` — live-mode-only startup recovery, called explicitly by `run_live.py` (Task 7) after construction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_paper_engine.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_engine.py -v`
Expected: FAIL with `AttributeError: 'PaperEngine' object has no attribute 'reconcile_live_position'`

- [ ] **Step 3: Write the implementation**

Add to `live/paper_engine.py` imports:

```python
from db.trades_db import get_trade_by_id, init_db, insert_trade_entry, load_daily_state, update_trade_exit
```

(replaces the Task 5 import line that only pulled in `init_db, insert_trade_entry, update_trade_exit`).

Add a new method to `PaperEngine`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_engine.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add live/paper_engine.py tests/test_paper_engine.py
git commit -m "feat: reconcile live positions against the broker on startup"
```

---

### Task 7: Shared ticker loop + `run_live.py` safety gates

**Files:**
- Create: `live/ticker_loop.py`
- Modify: `live/run_paper.py`
- Create: `live/run_live.py`
- Test: `tests/test_ticker_loop.py`, `tests/test_run_live_safety_gates.py`

**Interfaces:**
- Consumes: `LiveOrderManager` (Task 2), `PaperEngine.reconcile_live_position` (Task 6).
- Produces: `live.ticker_loop.run(engine, kite, token, square_off_time, set_stopped) -> None`. `live.run_live._check_safety_gates(args, cfg) -> None` (raises `SystemExit` on any failed gate).

- [ ] **Step 1: Extract the shared loop — write `live/ticker_loop.py`**

```python
"""Shared Kite WebSocket tick loop, used by both paper and live trading
entrypoints. Reconnects with backoff until the day's square-off time,
then keeps the process (and dashboard) alive."""
import logging
import time
from datetime import datetime, time as dt_time

from kiteconnect import KiteTicker

logger = logging.getLogger(__name__)


def _past_square_off(square_off_str: str) -> bool:
    now = datetime.now().time()
    sq = dt_time.fromisoformat(square_off_str)
    return now >= sq


def run(engine, kite, token: int, square_off_time: str, set_stopped) -> None:
    attempt = 0
    while True:
        if _past_square_off(square_off_time):
            logger.info(f"Past square-off time ({square_off_time}). Bot is done for the day. ✅")
            set_stopped()
            break

        attempt += 1
        logger.info(f"Connecting to WebSocket (attempt {attempt})...")

        kws = KiteTicker(kite.api_key, kite.access_token)

        def on_ticks(ws, ticks):
            if _past_square_off(square_off_time):
                logger.info("Square-off time reached. Closing WebSocket.")
                ws.close()
                return
            for tick in ticks:
                engine.on_tick(tick)

        def on_connect(ws, response):
            logger.info(f"WebSocket connected. Subscribing to token {token}...")
            ws.subscribe([token])
            ws.set_mode(ws.MODE_FULL, [token])

        def on_error(ws, code, reason):
            logger.warning(f"WebSocket error {code}: {reason}")

        def on_close(ws, code, reason):
            logger.info(f"WebSocket closed: {code} - {reason}")

        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_error = on_error
        kws.on_close = on_close

        try:
            kws.connect(threaded=True)
            while True:
                if _past_square_off(square_off_time):
                    logger.info("Bot done for the day. ✅")
                    kws.close()
                    set_stopped()
                    break
                if not kws.is_connected():
                    time.sleep(2)
                    if not kws.is_connected():
                        break
                time.sleep(1)
        except Exception as e:
            logger.error(f"WebSocket connection failed: {e}")

        if _past_square_off(square_off_time):
            break

        wait = min(30, 5 * attempt)
        logger.info(f"Reconnecting in {wait} seconds...")
        time.sleep(wait)

    logger.info("Trading is finished. Keeping dashboard alive... (Press Ctrl+C to close)")
    while True:
        time.sleep(1)
```

- [ ] **Step 2: Write the failing test for the pure-logic part**

Create `tests/test_ticker_loop.py`:

```python
from datetime import datetime

from live.ticker_loop import _past_square_off


def test_past_square_off_true_after_time(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 7, 18, 15, 21)

    monkeypatch.setattr("live.ticker_loop.datetime", _FixedDatetime)
    assert _past_square_off("15:20") is True


def test_past_square_off_false_before_time(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls):
            return datetime(2026, 7, 18, 15, 19)

    monkeypatch.setattr("live.ticker_loop.datetime", _FixedDatetime)
    assert _past_square_off("15:20") is False
```

Run: `pytest tests/test_ticker_loop.py -v`
Expected: PASS (already implemented in Step 1 — this locks the behavior in with a regression test)

- [ ] **Step 3: Update `live/run_paper.py` to delegate to the shared loop**

Replace everything from `def _past_square_off` through the end of `main()`'s `while True:` reconnect block (i.e. keep argument parsing, config/kite/token setup, historical fetch, `PaperEngine` construction, and dashboard startup exactly as they are) with:

```python
from live.ticker_loop import run as run_ticker_loop


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Live Paper Trader")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--port", type=int, default=5050, help="Dashboard port (default: 5050)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    square_off_time = cfg["trading_hours"]["square_off_time"]

    kite = get_kite_client()
    token = _resolve_sensex_token(kite, cfg["instrument"])

    today = datetime.now().strftime("%Y-%m-%d")
    logging.info(f"Fetching seed data for {today}...")
    try:
        import pandas as pd
        df_1m = fetch_historical(kite, token, today, today, interval="minute")
        if df_1m.empty:
            logging.info("No candles yet (pre-market). Bot will start trading at 09:25 when the market opens.")
        else:
            logging.info(f"Fetched {len(df_1m)} historical 1-minute candles.")
    except Exception as e:
        logging.warning(f"Could not fetch historical data: {e}. Starting with empty dataframe.")
        import pandas as pd
        df_1m = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], name="datetime")
        )

    engine = PaperEngine(instrument_token=token, df_1m=df_1m, cfg=cfg, kite=kite)

    started_at = datetime.now()
    set_engine(engine, started_at)
    start_server(port=args.port)
    logging.info(f"Dashboard running at http://localhost:{args.port}")

    run_ticker_loop(engine, kite, token, square_off_time, set_stopped)
```

Remove the now-unused `_past_square_off` function and the `KiteTicker` import from `run_paper.py` (both moved into `ticker_loop.py`); `main()`'s `try/except KeyboardInterrupt` wrapper at the bottom of the file stays unchanged.

- [ ] **Step 4: Verify `run_paper.py` still imports cleanly**

Run: `python -c "import ast; ast.parse(open('live/run_paper.py').read())"`
Expected: no output (valid syntax)

Run: `python -m py_compile live/run_paper.py live/ticker_loop.py`
Expected: no output (compiles cleanly)

- [ ] **Step 5: Write `live/run_live.py`**

```python
"""CLI entry point: run LIVE real-money trading for the current day.

    python -m live.run_live --live

Requires ALL of:
  - the --live flag on this command
  - config.yaml: execution.mode == "live"
  - config.yaml: execution.confirm_live == true

Any one missing refuses to start, naming which gate failed.
"""
import argparse
import logging
from datetime import datetime

from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical
from backtest.run_backtest import _resolve_sensex_token
from execution.order_manager import LiveOrderManager
from live.paper_engine import PaperEngine
from live.api import start_server, set_engine, set_stopped
from live.ticker_loop import run as run_ticker_loop
from utils.config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)

logger = logging.getLogger(__name__)


def _check_safety_gates(args, cfg: dict) -> None:
    execution_cfg = cfg.get("execution", {})
    failures = []
    if not args.live:
        failures.append("the --live CLI flag was not passed")
    if execution_cfg.get("mode") != "live":
        failures.append("config.yaml execution.mode is not 'live'")
    if not execution_cfg.get("confirm_live"):
        failures.append("config.yaml execution.confirm_live is not true")
    if failures:
        raise SystemExit(
            "Refusing to start live trading — all of these must be true:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LIVE real-money trading")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--live", action="store_true", help="Required to actually place real orders")
    args = parser.parse_args()

    cfg = load_config(args.config)
    _check_safety_gates(args, cfg)

    square_off_time = cfg["trading_hours"]["square_off_time"]

    kite = get_kite_client()
    token = _resolve_sensex_token(kite, cfg["instrument"])

    today = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"Fetching seed data for {today}...")
    try:
        df_1m = fetch_historical(kite, token, today, today, interval="minute")
    except Exception as e:
        logger.warning(f"Could not fetch historical data: {e}. Starting with empty dataframe.")
        import pandas as pd
        df_1m = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], name="datetime"),
        )

    engine = PaperEngine(
        instrument_token=token, df_1m=df_1m, cfg=cfg, kite=kite,
        order_manager=LiveOrderManager(kite), mode="live",
    )
    engine.reconcile_live_position()
    if engine.trading_halted_today:
        logger.critical("Live trading is HALTED after startup reconciliation — see the log above for why.")

    started_at = datetime.now()
    set_engine(engine, started_at)
    start_server(port=args.port)
    logger.info(f"LIVE trading dashboard running at http://localhost:{args.port}")

    run_ticker_loop(engine, kite, token, square_off_time, set_stopped)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nForce closing by user...")
        import os
        os._exit(0)
```

- [ ] **Step 6: Write the failing tests for the safety gates**

Create `tests/test_run_live_safety_gates.py`:

```python
import argparse

import pytest

from live.run_live import _check_safety_gates


def _args(live=True):
    ns = argparse.Namespace()
    ns.live = live
    return ns


def test_all_gates_pass_does_not_raise():
    cfg = {"execution": {"mode": "live", "confirm_live": True}}
    _check_safety_gates(_args(live=True), cfg)  # should not raise


def test_missing_cli_flag_blocks():
    cfg = {"execution": {"mode": "live", "confirm_live": True}}
    with pytest.raises(SystemExit, match="--live"):
        _check_safety_gates(_args(live=False), cfg)


def test_missing_config_mode_blocks():
    cfg = {"execution": {"mode": "paper", "confirm_live": True}}
    with pytest.raises(SystemExit, match="execution.mode"):
        _check_safety_gates(_args(live=True), cfg)


def test_missing_confirm_live_blocks():
    cfg = {"execution": {"mode": "live", "confirm_live": False}}
    with pytest.raises(SystemExit, match="confirm_live"):
        _check_safety_gates(_args(live=True), cfg)


def test_missing_execution_section_blocks():
    cfg = {}
    with pytest.raises(SystemExit):
        _check_safety_gates(_args(live=True), cfg)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_ticker_loop.py tests/test_run_live_safety_gates.py -v`
Expected: PASS (7 tests total)

- [ ] **Step 8: Run the full suite for a regression check**

Run: `pytest -v`
Expected: PASS (all)

- [ ] **Step 9: Commit**

```bash
git add live/ticker_loop.py live/run_paper.py live/run_live.py tests/test_ticker_loop.py tests/test_run_live_safety_gates.py
git commit -m "feat: run_live.py entrypoint with three-gate safety check, shared ws loop"
```

---

### Task 8: Kill switch

**Files:**
- Modify: `live/paper_engine.py`
- Modify: `live/api.py`
- Create: `live/kill_switch.py`
- Test: `tests/test_paper_engine.py`, `tests/test_kill_switch_api.py`

**Interfaces:**
- Consumes: `set_daily_halt` (Task 4).
- Produces: `PaperEngine.kill(reason: str = "manual kill switch") -> dict` with keys `closed_position`, `halted`. `POST /api/kill` on the Flask app in `live/api.py`.

- [ ] **Step 1: Write the failing engine-level tests**

Append to `tests/test_paper_engine.py`:

```python
def test_kill_closes_open_position_and_halts(tmp_path):
    om = _StubOrderManager(entry_price=150.0, exit_price=180.0)
    engine = _make_engine(tmp_path, order_manager=om, mode="live")
    engine._enter_trade(Signal(direction="BUY_CALL", reasons=["test"]))
    assert engine.open_trade is not None

    result = engine.kill(reason="test kill")

    assert result == {"closed_position": True, "halted": True}
    assert engine.open_trade is None
    assert engine.trading_halted_today is True


def test_kill_with_no_open_position_just_halts(tmp_path):
    engine = _make_engine(tmp_path, order_manager=_StubOrderManager(), mode="live")

    result = engine.kill(reason="test kill")

    assert result == {"closed_position": False, "halted": True}
    assert engine.trading_halted_today is True


def test_kill_persists_halt_across_reconciliation(tmp_path):
    db_path = str(tmp_path / "trades.sqlite3")
    engine = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=_FakeKitePositions([]),
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state.json"),
    )
    engine.current_day = pd.Timestamp("2026-07-18").date()
    engine.kill(reason="test kill")

    engine2 = PaperEngine(
        instrument_token=1, df_1m=_flat_df(), cfg=CFG, kite=_FakeKitePositions([]),
        order_manager=_StubOrderManager(), mode="live", db_path=db_path,
        state_path=str(tmp_path / "paper_state2.json"),
    )
    engine2.current_day = pd.Timestamp("2026-07-18").date()
    engine2.reconcile_live_position()

    assert engine2.trading_halted_today is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_paper_engine.py -v`
Expected: FAIL with `AttributeError: 'PaperEngine' object has no attribute 'kill'`

- [ ] **Step 3: Implement `PaperEngine.kill`**

Add to `live/paper_engine.py` imports:

```python
from db.trades_db import get_trade_by_id, init_db, insert_trade_entry, load_daily_state, set_daily_halt, update_trade_exit
```

Add the method:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paper_engine.py -v`
Expected: PASS (all)

- [ ] **Step 5: Write the failing API test**

Create `tests/test_kill_switch_api.py`:

```python
import live.api as api_module


class _StubEngine:
    def __init__(self):
        self.killed_with = None

    def kill(self, reason):
        self.killed_with = reason
        return {"closed_position": False, "halted": True}


def test_kill_endpoint_calls_engine_kill():
    api_module._engine = _StubEngine()
    client = api_module.app.test_client()

    resp = client.post("/api/kill")

    assert resp.status_code == 200
    assert resp.get_json() == {"closed_position": False, "halted": True}
    assert api_module._engine.killed_with == "dashboard kill switch"


def test_kill_endpoint_without_engine_returns_400():
    api_module._engine = None
    client = api_module.app.test_client()

    resp = client.post("/api/kill")

    assert resp.status_code == 400
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_kill_switch_api.py -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 7: Add the endpoint to `live/api.py`**

Add after the existing `/api/monthly` route:

```python
@app.route("/api/kill", methods=["POST"])
def kill():
    if _engine is None:
        return jsonify({"error": "no engine running"}), 400
    result = _engine.kill(reason="dashboard kill switch")
    return jsonify(result)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_kill_switch_api.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Write the CLI kill switch client**

Create `live/kill_switch.py`:

```python
"""Manual kill switch: immediately halts live trading and, if a position
is open, market-exits it.

    python -m live.kill_switch --port 5050
"""
import argparse
import sys
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Flatten and halt the running live bot")
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    req = urllib.request.Request(f"http://localhost:{args.port}/api/kill", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(resp.read().decode())
    except Exception as e:
        print(f"Kill switch request failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 10: Verify it compiles**

Run: `python -m py_compile live/kill_switch.py`
Expected: no output

- [ ] **Step 11: Run the full suite for a regression check**

Run: `pytest -v`
Expected: PASS (all)

- [ ] **Step 12: Commit**

```bash
git add live/paper_engine.py live/api.py live/kill_switch.py tests/test_paper_engine.py tests/test_kill_switch_api.py
git commit -m "feat: manual kill switch to flatten and halt live trading"
```

---

### Task 9: Config, `.gitignore`, and README

**Files:**
- Modify: `config/config.yaml`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: `execution.mode` / `execution.confirm_live` (read by `run_live.py`'s `_check_safety_gates`, Task 7).

- [ ] **Step 1: Add the `execution` section to `config/config.yaml`**

Add a new top-level section (after `instrument:`, before `timeframes:`):

```yaml
execution:
  mode: "paper"         # "paper" or "live" — live also requires the --live CLI flag AND confirm_live below
  confirm_live: false   # extra explicit opt-in required before live.run_live will place a single real order
```

- [ ] **Step 2: Run the config test to confirm it still loads correctly**

Run: `pytest tests/test_config.py -v`
Expected: PASS (unaffected — adds a section, doesn't change existing ones)

- [ ] **Step 3: Ignore the new runtime SQLite file**

In `.gitignore`, add:

```
*.sqlite3
```

- [ ] **Step 4: Add a Phase 2 section to `README.md`**

After the existing "## Run a backtest" section and before "## What's not here yet", add:

```markdown
## Phase 2 — live paper trading and real orders

Run the live paper trader (simulated fills, real market data, no real
orders):

```bash
python -m live.run_paper
```

Open `http://localhost:5050` for the live dashboard.

### Going live (real money, real orders)

`live.run_live` requires **all three** of the following, or it refuses to
start:

1. The `--live` CLI flag.
2. `config.yaml`: `execution.mode: live`
3. `config.yaml`: `execution.confirm_live: true`

```bash
python -m live.run_live --live
```

**Before your first live run**, review `config/config.yaml`:

- `instrument.lot_size` — must match the real SENSEX weekly options lot
  size, not the placeholder value.
- `risk.risk_pct` and `risk.max_daily_loss_pct` — the checked-in values
  are elevated test settings, not real-money position-sizing/loss-limit
  numbers.

### Kill switch

To immediately flatten any open position and halt trading for the rest
of the day, either click "Flatten & Halt" on the dashboard, or run:

```bash
python -m live.kill_switch --port 5050
```

The halt persists across a restart (backed by `db/trades.sqlite3`) —
you must explicitly clear `daily_halt` for the day to resume.
```

Update the existing "## What's not here yet" section's Phase 2 bullets to reflect what's now done:

```markdown
## What's not here yet

- Telegram alerts (Phase 3)
```

(remove the "Live/paper order execution..." and "SQLite trade logging..." bullets — both now shipped — and the daily-halt-persistence bullet, since Task 4/6 now cover it).

- [ ] **Step 5: Commit**

```bash
git add config/config.yaml .gitignore README.md
git commit -m "docs: Phase 2 README section, execution config, gitignore sqlite"
```

---

## Self-Review Notes

- **Spec coverage:** `execution/order_manager.py` (Tasks 1-2) covers the Order Manager section; `db/trades_db.py` (Tasks 3-4) covers the SQLite trade log and halt-state rebuild; Task 5 covers `PaperEngine` wiring plus the live-mode option-premium P&L fix (needed for real-money halt thresholds to be correct, an addition the design doc implied but didn't spell out numerically); Task 6 covers startup reconciliation (both the matching and orphaned-position cases); Task 7 covers `run_live.py`'s three-gate safety check and the shared websocket loop; Task 8 covers the kill switch (engine method, API route, CLI); Task 9 covers config/docs. All design doc sections have a corresponding task.
- **Type consistency:** `Fill`, `OrderManager.submit_entry/submit_exit(option_symbol, quantity) -> Fill` signatures are identical across `PaperOrderManager` (Task 1), `LiveOrderManager` (Task 2), and every stub used in `PaperEngine` tests (Tasks 5-8). `db_path`/`mode`/`state_path` constructor parameters introduced in Task 5 are reused unchanged in Tasks 6 and 8.
- **No live-money integration test** places a real order against Kite — that's not automatable safely. The first real-money run should be a small-size, market-hours, human-watching-the-dashboard manual smoke test; this is called out in the README but is deliberately not a task here.
