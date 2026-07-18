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
