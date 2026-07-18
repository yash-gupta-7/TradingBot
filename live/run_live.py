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
