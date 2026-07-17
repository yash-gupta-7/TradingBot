"""Debug why no trades were generated for a given date.

Uses prior-day pre-seeded data (same as run_backtest) so indicators are
warm from the first bar of the target day. Reports per-bar rejection reasons.

Run with:
    python -m backtest.debug_signals --from 2026-07-16 --to 2026-07-16
"""
import argparse
from collections import Counter
from datetime import time as dt_time

import pandas as pd

from kite.auth import get_kite_client
from backtest.data_loader import fetch_with_warmup, resample_to_5min
from backtest.run_backtest import _resolve_sensex_token
from indicators.ema import calculate_ema, ema_slope, ema_cross_signal
from indicators.supertrend import supertrend, supertrend_agree
from utils.config import load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", required=True)
    parser.add_argument("--to", dest="to_date", required=True)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    kite = get_kite_client()
    token = _resolve_sensex_token(kite, cfg["instrument"])

    # Fetch with 7 days of prior-day warmup data so indicators are ready at 09:15
    df_1m, live_from = fetch_with_warmup(
        kite, token, args.from_date, args.to_date, warmup_days=7
    )
    live_bars = len(df_1m[df_1m.index >= live_from])
    print(
        f"Fetched {len(df_1m)} 1-minute candles "
        f"({len(df_1m) - live_bars} warmup from prior days + {live_bars} live)\n"
    )

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

        # Skip prior-day warmup bars — don't count them as rejections
        if now < live_from:
            continue

        # Skip outside trading hours
        t = now.time()
        in_window = any(s <= t <= e for s, e in trading_windows)
        if not in_window:
            continue

        # 5-min window (closed bars only)
        window_5m = df_5m[df_5m.index + pd.Timedelta(minutes=5) <= now]

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
        slope_slow = ema_slope(ema_slow, ind["ema_slope_lookback"])
        ema_sig = ema_cross_signal(
            ema_fast, ema_slow, slope_fast, slope_slow, ind["ema_slope_threshold"]
        )
        if ema_sig != st_trend_1m:
            reject_reasons["ema_cross_mismatch"] += 1
            continue

        signal_count += 1
        print(f"  SIGNAL at {now}: {st_trend_1m} | slope_fast={slope_fast:.2f} slope_slow={slope_slow:.2f}")

    print(f"\n--- Summary for {args.from_date} to {args.to_date} ---")
    print(f"Total signals generated (inside trading hours): {signal_count}")
    print("\nRejection reasons (bars that passed trading-hours filter):")
    for reason, count in reject_reasons.most_common():
        print(f"  {reason}: {count}")


if __name__ == "__main__":
    main()
