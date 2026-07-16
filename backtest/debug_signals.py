"""Debug why no trades were generated for a given date.

Run with:
    python -m backtest.debug_signals --from 2026-07-16 --to 2026-07-16
"""
import argparse
from collections import Counter

import pandas as pd

from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical, resample_to_5min
from backtest.run_backtest import _resolve_sensex_token
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend, supertrend_agree
from utils.config import load_config
from datetime import time as dt_time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    kite = get_kite_client()
    token = _resolve_sensex_token(kite, cfg["instrument"])

    df_1m = fetch_historical(kite, token, args.from_date, args.to_date, interval="minute")
    print(f"Fetched {len(df_1m)} 1-minute candles\n")

    df_5m = resample_to_5min(df_1m)
    warmup = cfg["backtest"]["warmup_bars"]
    ind = cfg["indicators"]

    reject_reasons = Counter()
    signal_count = 0

    trading_windows = [
        (dt_time.fromisoformat(s), dt_time.fromisoformat(e))
        for s, e in cfg["trading_hours"]["windows"]
    ]

    for i in range(warmup, len(df_1m)):
        window_1m = df_1m.iloc[: i + 1]
        now = window_1m.index[-1]

        # Skip outside trading hours
        t = now.time()
        in_window = any(s <= t <= e for s, e in trading_windows)
        if not in_window:
            continue

        # 5-min window (closed bars only)
        window_5m = df_5m[df_5m.index + pd.Timedelta(minutes=5) <= now]
        if len(window_5m) < warmup:
            reject_reasons["insufficient_5m_bars"] += 1
            continue

        # --- 5-min higher trend ---
        st1_5m = supertrend(window_5m, **ind["supertrend_fast"])
        st2_5m = supertrend(window_5m, **ind["supertrend_slow"])
        higher_trend = supertrend_agree(st1_5m["trend"].iloc[-1], st2_5m["trend"].iloc[-1])
        if higher_trend is None:
            reject_reasons["5m_trend_undecided"] += 1
            continue

        # --- 1-min supertrend ---
        st1_1m = supertrend(window_1m, **ind["supertrend_fast"])
        st2_1m = supertrend(window_1m, **ind["supertrend_slow"])
        st_trend_1m = supertrend_agree(st1_1m["trend"].iloc[-1], st2_1m["trend"].iloc[-1])
        if st_trend_1m is None:
            reject_reasons["1m_trend_undecided"] += 1
            continue
        if st_trend_1m != higher_trend:
            reject_reasons["1m_vs_5m_trend_mismatch"] += 1
            continue

        # --- EMA cross ---
        ema_fast = calculate_ema(window_1m["close"], ind["ema_fast_length"])
        ema_slow = calculate_ema(window_1m["close"], ind["ema_slow_length"])
        slope_fast = ema_slope(ema_fast, ind["ema_slope_lookback"])
        ema_sig = ema_cross_signal(ema_fast, ema_slow, slope_fast, ind["ema_slope_threshold"])
        if ema_sig != st_trend_1m:
            reject_reasons["ema_cross_mismatch"] += 1
            continue

        signal_count += 1
        print(f"  SIGNAL at {now}: {st_trend_1m} | slope={slope_fast:.4f}")

    print(f"\n--- Summary for {args.from_date} to {args.to_date} ---")
    print(f"Total signals generated (inside trading hours): {signal_count}")
    print("\nRejection reasons (bars that passed trading-hours filter):")
    for reason, count in reject_reasons.most_common():
        print(f"  {reason}: {count}")


if __name__ == "__main__":
    main()
