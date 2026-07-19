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


def _trade_to_dict(t, mode: str = "paper"):
    pnl = t.realized_pnl(mode)
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
        "option_symbol": getattr(t, "option_symbol", None),
        "option_entry_price": round(float(t.option_entry_price), 2) if getattr(t, "option_entry_price", None) else None,
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
    return jsonify([_trade_to_dict(t, _engine.mode) for t in reversed(_engine.trades)])


@app.route("/api/monthly")
def monthly():
    if _engine is None:
        return jsonify({"months": {}, "total_pnl": 0, "total_trades": 0, "wins": 0, "losses": 0})

    from collections import defaultdict
    months: dict[str, dict] = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})

    # Real (mode-aware) P&L per trade, computed once and reused below so the
    # dashboard shows actual rupees for live trades, not fabricated
    # index-point P&L (backtest.engine.Trade.pnl).
    trade_pnls = [(t, t.realized_pnl(_engine.mode)) for t in _engine.trades]

    for t, pnl in trade_pnls:
        if t.exit_time is None or pnl is None:
            continue
        month_key = t.exit_time.strftime("%b %Y")
        months[month_key]["pnl"] += pnl
        months[month_key]["trades"] += 1
        if pnl >= 0:
            months[month_key]["wins"] += 1
        else:
            months[month_key]["losses"] += 1

    total_pnl = sum(pnl for _, pnl in trade_pnls if pnl is not None)
    wins = sum(1 for _, pnl in trade_pnls if pnl is not None and pnl >= 0)
    losses = sum(1 for _, pnl in trade_pnls if pnl is not None and pnl < 0)

    return jsonify({
        "months": {k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                        "wins": v["wins"], "losses": v["losses"]}
                   for k, v in months.items()},
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(_engine.trades),
        "wins": wins,
        "losses": losses,
    })


@app.route("/api/kill", methods=["POST"])
def kill():
    if _engine is None:
        return jsonify({"error": "no engine running"}), 400
    result = _engine.kill(reason="dashboard kill switch")
    return jsonify(result)


@app.route("/api/backtest", methods=["POST"])
def run_backtest():
    """Run a walk-forward backtest over a date range and return full results.

    Request JSON: { "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD" }
    Response JSON: { trades: [...], metrics: {...}, monthly_returns: {...},
                     warmup_bars: N, live_bars: N }
    """
    from flask import request
    from collections import defaultdict

    body = request.get_json(silent=True) or {}
    from_date = body.get("from_date", "")
    to_date = body.get("to_date", "")

    if not from_date or not to_date:
        return jsonify({"error": "from_date and to_date are required"}), 400

    try:
        # Lazy imports so the live server doesn't load backtest deps at startup
        from kite.auth import get_kite_client
        from backtest.data_loader import fetch_with_warmup
        from backtest.engine import BacktestEngine
        from backtest.metrics import compute_metrics
        from utils.config import load_config

        cfg = load_config("config/config.yaml")
        kite = get_kite_client()

        # Resolve SENSEX instrument token
        instruments = kite.instruments(cfg["instrument"]["exchange"])
        match = next(
            i for i in instruments
            if i["tradingsymbol"] == cfg["instrument"]["index_symbol"]
            and i["segment"] == "INDICES"
        )
        token = match["instrument_token"]

        df_1m, live_from = fetch_with_warmup(
            kite, token, from_date, to_date, warmup_days=7
        )
        live_bars = int(len(df_1m[df_1m.index >= live_from]))
        warmup_bars_count = int(len(df_1m)) - live_bars

        engine = BacktestEngine(df_1m, cfg, live_from=live_from, kite=kite)
        bt_trades = engine.run()
        metrics = compute_metrics(bt_trades)

        # Build monthly breakdown
        months: dict[str, dict] = defaultdict(
            lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        )
        for t in bt_trades:
            if t.exit_time is None or t.pnl is None:
                continue
            mk = t.exit_time.strftime("%Y-%m")
            months[mk]["pnl"] += t.pnl
            months[mk]["trades"] += 1
            if t.pnl >= 0:
                months[mk]["wins"] += 1
            else:
                months[mk]["losses"] += 1

        trade_list = [_trade_to_dict(t) for t in reversed(bt_trades)]

        # Remove non-JSON-serialisable keys from metrics
        safe_metrics = {
            k: (round(float(v), 4) if isinstance(v, float) else v)
            for k, v in metrics.items()
            if k not in ("equity_curve",)
        }

        return jsonify({
            "trades": trade_list,
            "metrics": safe_metrics,
            "monthly_returns": {
                k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                    "wins": v["wins"], "losses": v["losses"]}
                for k, v in months.items()
            },
            "total_candles": int(len(df_1m)),
            "warmup_bars": warmup_bars_count,
            "live_bars": live_bars,
        })

    except StopIteration:
        return jsonify({"error": "SENSEX instrument not found on exchange"}), 500
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "detail": traceback.format_exc()}), 500


def start_server(port: int = 5050):
    """Start Flask in a background daemon thread."""
    t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    return t
