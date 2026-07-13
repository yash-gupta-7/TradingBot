"""CLI entry point: fetch SENSEX historical data and run the backtest.

    python -m backtest.run_backtest --from 2026-06-01 --to 2026-07-01
"""
import argparse
import json

from kite.auth import get_kite_client
from backtest.data_loader import fetch_historical
from backtest.engine import BacktestEngine
from backtest.metrics import compute_metrics
from utils.config import load_config


def _resolve_sensex_token(kite, instrument_cfg: dict) -> int:
    instruments = kite.instruments(instrument_cfg["exchange"])
    match = next(
        i for i in instruments
        if i["tradingsymbol"] == instrument_cfg["index_symbol"] and i["segment"] == "INDICES"
    )
    return match["instrument_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the SENSEX signal engine")
    parser.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    kite = get_kite_client()
    token = _resolve_sensex_token(kite, cfg["instrument"])

    df_1m = fetch_historical(kite, token, args.from_date, args.to_date, interval="minute")
    print(f"Fetched {len(df_1m)} 1-minute candles from {args.from_date} to {args.to_date}")

    engine = BacktestEngine(df_1m, cfg)
    trades = engine.run()
    metrics = compute_metrics(trades)

    print(f"\nTrades: {len(trades)}")
    print(json.dumps({k: v for k, v in metrics.items() if k not in ("equity_curve", "monthly_returns")}, indent=2))
    print("Monthly returns:", json.dumps(metrics["monthly_returns"], indent=2))


if __name__ == "__main__":
    main()
