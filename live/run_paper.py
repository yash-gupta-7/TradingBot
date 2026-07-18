"""CLI entry point: run paper trading for the current day using websockets.

    python -m live.run_paper
"""
import argparse
import logging
import time
import os
from datetime import datetime, time as dt_time

from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical
from live.paper_engine import PaperEngine
from live.api import start_server, set_engine, set_stopped
from utils.config import load_config
from backtest.run_backtest import _resolve_sensex_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ]
)

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


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nForce closing by user...")
        os._exit(0)
