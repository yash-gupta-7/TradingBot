"""Standalone Flask server for the Backtest dashboard tab.

Start this instead of run_paper.py when you only want to run backtests
from the UI — no WebSocket, no live trading needed.

    python -m live.run_backtest_server
    # Then open http://localhost:5050 in your browser
"""
import threading
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import os

app = Flask(__name__, static_folder=os.path.dirname(__file__))
CORS(app)


@app.route("/")
def index():
    return send_from_directory(os.path.dirname(__file__), "dashboard.html")


# ── Stub live-trading endpoints so the dashboard doesn't show errors ──────────

@app.route("/api/status")
def status():
    return jsonify({
        "running": False,
        "started_at": None,
        "capital": None,
        "trades_today": 0,
        "trading_halted": False,
        "open_trade": None,
        "consecutive_losses": 0,
    })


@app.route("/api/trades")
def trades():
    return jsonify([])


@app.route("/api/monthly")
def monthly():
    return jsonify({"months": {}, "total_pnl": 0, "total_trades": 0, "wins": 0, "losses": 0})


# ── Backtest endpoint ──────────────────────────────────────────────────────────

@app.route("/api/backtest", methods=["POST"])
def run_backtest():
    """Run a walk-forward backtest over a date range.

    Request JSON: { "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD" }
    """
    from collections import defaultdict

    body = request.get_json(silent=True) or {}
    from_date = body.get("from_date", "")
    to_date   = body.get("to_date", "")

    if not from_date or not to_date:
        return jsonify({"error": "from_date and to_date are required"}), 400

    try:
        from kite.auth import get_kite_client
        from backtest.data_loader import fetch_with_warmup
        from backtest.engine import BacktestEngine
        from backtest.metrics import compute_metrics
        from utils.config import load_config

        cfg   = load_config("config/config.yaml")
        kite  = get_kite_client()

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
        live_bars         = int(len(df_1m[df_1m.index >= live_from]))
        warmup_bars_count = int(len(df_1m)) - live_bars

        engine    = BacktestEngine(df_1m, cfg, live_from=live_from)
        bt_trades = engine.run()
        metrics   = compute_metrics(bt_trades)

        # Monthly breakdown
        months: dict = defaultdict(lambda: {"pnl": 0.0, "trades": 0, "wins": 0, "losses": 0})
        for t in bt_trades:
            if t.exit_time is None or t.pnl is None:
                continue
            mk = t.exit_time.strftime("%Y-%m")
            months[mk]["pnl"]    += t.pnl
            months[mk]["trades"] += 1
            if t.pnl >= 0:
                months[mk]["wins"]   += 1
            else:
                months[mk]["losses"] += 1

        def _td(t):
            pnl = t.pnl
            return {
                "entry_time":    t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else None,
                "exit_time":     t.exit_time.strftime("%Y-%m-%d %H:%M")  if t.exit_time  else None,
                "direction":     t.direction,
                "entry_price":   round(float(t.entry_price), 2),
                "exit_price":    round(float(t.exit_price), 2) if t.exit_price else None,
                "quantity":      int(t.quantity),
                "stop_price":    round(float(t.stop_price), 2),
                "target_price":  round(float(t.target_price), 2),
                "exit_reason":   t.exit_reason,
                "pnl":           round(float(pnl), 2) if pnl is not None else None,
                "entry_reasons": t.entry_reasons,
            }

        safe_metrics = {
            k: (round(float(v), 4) if isinstance(v, float) else v)
            for k, v in metrics.items()
            if k not in ("equity_curve",)
        }

        return jsonify({
            "trades":         [_td(t) for t in reversed(bt_trades)],
            "metrics":        safe_metrics,
            "monthly_returns": {
                k: {"pnl": round(v["pnl"], 2), "trades": v["trades"],
                    "wins": v["wins"], "losses": v["losses"]}
                for k, v in months.items()
            },
            "total_candles": int(len(df_1m)),
            "warmup_bars":   warmup_bars_count,
            "live_bars":     live_bars,
        })

    except StopIteration:
        return jsonify({"error": "SENSEX instrument not found on exchange"}), 500
    except Exception as exc:
        import traceback
        return jsonify({"error": str(exc), "detail": traceback.format_exc()}), 500


# ── Main ───────────────────────────────────────────────────────────────────────

def main(port: int = 5050):
    import webbrowser
    print(f"\n[*] Backtest server starting at http://localhost:{port}")
    print("    Open your browser to that URL, then click the Backtest tab.\n")
    # Open browser after a short delay so Flask is up
    threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
