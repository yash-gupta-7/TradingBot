"""CLI entry point: run paper trading for the current day using websockets.

    python -m live.run_paper
"""
import argparse
import logging
import time
import os
from datetime import datetime, time as dt_time

from kiteconnect import KiteTicker

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


def _past_square_off(square_off_str: str) -> bool:
    now = datetime.now().time()
    sq = dt_time.fromisoformat(square_off_str)
    return now >= sq


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

    # Start dashboard API
    started_at = datetime.now()
    set_engine(engine, started_at)
    start_server(port=args.port)
    logging.info(f"Dashboard running at http://localhost:{args.port}")

    attempt = 0
    while True:
        # Stop entirely after square-off time
        if _past_square_off(square_off_time):
            logging.info(f"Past square-off time ({square_off_time}). Bot is done for the day. ✅")
            set_stopped()
            break

        attempt += 1
        logging.info(f"Connecting to WebSocket (attempt {attempt})...")

        kws = KiteTicker(kite.api_key, kite.access_token)

        def on_ticks(ws, ticks):
            # Check if we've passed square-off — if so, disconnect
            if _past_square_off(square_off_time):
                logging.info("Square-off time reached. Closing WebSocket.")
                ws.close()
                return
            for tick in ticks:
                engine.on_tick(tick)

        def on_connect(ws, response):
            logging.info(f"WebSocket connected. Subscribing to token {token}...")
            ws.subscribe([token])
            ws.set_mode(ws.MODE_FULL, [token])

        def on_error(ws, code, reason):
            logging.warning(f"WebSocket error {code}: {reason}")

        def on_close(ws, code, reason):
            logging.info(f"WebSocket closed: {code} - {reason}")

        kws.on_ticks = on_ticks
        kws.on_connect = on_connect
        kws.on_error = on_error
        kws.on_close = on_close

        try:
            kws.connect(threaded=True)
            while True:
                if _past_square_off(square_off_time):
                    logging.info("Bot done for the day. ✅")
                    kws.close()
                    set_stopped()
                    break
                
                # If websocket drops, break out to trigger the reconnect loop
                if not kws.is_connected():
                    # Short delay to allow connect() to finish its initial handshake
                    time.sleep(2)
                    if not kws.is_connected():
                        break
                        
                time.sleep(1)
        except Exception as e:
            logging.error(f"WebSocket connection failed: {e}")

        if _past_square_off(square_off_time):
            break

        wait = min(30, 5 * attempt)
        logging.info(f"Reconnecting in {wait} seconds...")
        time.sleep(wait)
    
    # Keep the main thread alive so the dashboard remains accessible
    logging.info("Trading is finished. Keeping dashboard alive... (Press Ctrl+C to close)")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nForce closing by user...")
        os._exit(0)
