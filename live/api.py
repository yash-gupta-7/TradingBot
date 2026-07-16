"""Flask API server for the paper trading dashboard.
Runs in a background thread alongside the WebSocket loop.
"""
import threading
from datetime import datetime, date
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import os

app = Flask(__name__, static_folder=os.path.dirname(__file__))
CORS(app)

# Global reference to PaperEngine — set by run_paper.py after engine is created
_engine = None
_started_at: datetime | None = None
_is_running = False


def set_engine(engine, started_at: datetime):
    global _engine, _started_at, _is_running
    _engine = engine
    _started_at = started_at
    _is_running = True


def set_stopped():
    global _is_running
    _is_running = False


def _trade_to_dict(t):
    pnl = t.pnl
    return {
        "entry_time": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else None,
        "exit_time": t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else None,
        "direction": t.direction,
        "entry_price": round(float(t.entry_price), 2),
        "exit_price": round(float(t.exit_price), 2) if t.exit_price else None,
        "quantity": int(t.quantity),
        "stop_price": round(float(t.stop_price), 2),
        "target_price": round(float(t.target_price), 2),
        "exit_reason": t.exit_reason,
        "pnl": round(float(pnl), 2) if pnl is not None else None,
        "entry_reasons": t.entry_reasons,
    }


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "dashboard.html")


@app.route("/api/status")
def status():
    if _engine is None:
        return jsonify({"running": False, "started_at": None, "capital": None,
                        "trades_today": 0, "trading_halted": False, "open_trade": None})

    open_trade = None
    if _engine.open_trade:
        t = _engine.open_trade
        open_trade = {
            "direction": t.direction,
            "entry_price": round(float(t.entry_price), 2),
            "entry_time": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else None,
            "stop_price": round(float(t.stop_price), 2),
            "target_price": round(float(t.target_price), 2),
            "quantity": int(t.quantity),
        }

    return jsonify({
        "running": _is_running,
        "started_at": _started_at.strftime("%Y-%m-%d %H:%M:%S") if _started_at else None,
        "capital": round(float(_engine.capital), 2),
        "initial_capital": round(float(_engine.day_start_capital), 2),
        "trades_today": _engine.trades_today,
        "trading_halted": _engine.trading_halted_today,
        "open_trade": open_trade,
        "consecutive_losses": _engine.consecutive_losses,
    })


@app.route("/api/trades")
def trades():
    if _engine is None:
        return jsonify([])
    return jsonify([_trade_to_dict(t) for t in reversed(_engine.trades)])


@app.route("/api/monthly")
def monthly():
    if _engine is None:
        return jsonify({"months": {}, "total_pnl": 0, "total_trades": 0, "wins": 0, "losses": 0})

    from collections import defaultdict
    months: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})

    for t in _engine.trades:
        if t.exit_time is None or t.pnl is None:
            continue
        month_key = t.exit_time.strftime("%b %Y")
        months[month_key]["pnl"] += t.pnl
        months[month_key]["trades"] += 1
        if t.pnl >= 0:
            months[month_key]["wins"] += 1
        else:
            months[month_key]["losses"] += 1

    total_pnl = sum(t.pnl for t in _engine.trades if t.pnl is not None)
    wins = sum(1 for t in _engine.trades if t.pnl is not None and t.pnl >= 0)
    losses = sum(1 for t in _engine.trades if t.pnl is not None and t.pnl < 0)

    return jsonify({
        "months": {k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                        "wins": v["wins"], "losses": v["losses"]}
                   for k, v in months.items()},
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(_engine.trades),
        "wins": wins,
        "losses": losses,
    })


def start_server(port: int = 5050):
    """Start Flask in a background daemon thread."""
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    return t
