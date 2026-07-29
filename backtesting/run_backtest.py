# ============================================================
#  backtesting/run_backtest.py — CLI backtest entrypoint
# ============================================================
#
#  Usage:
#    # 1) Ek baar historical data cache karo (MT5 chahiye):
#    python -m backtesting.run_backtest --fetch --days 60
#
#    # 2) Cached data par backtest chalao (MT5 nahi chahiye):
#    python -m backtesting.run_backtest --run
#
#    # Confidence gate off kar ke raw strategy dekhna ho:
#    python -m backtesting.run_backtest --run --no-gate
# ============================================================

import argparse
from datetime import datetime, timezone, timedelta

import config
from backtesting import data_loader
from backtesting.engine import GoldBacktest

TIMEFRAMES = ["D1", "H1", "M30", "M15", "M5", "M1"]


def do_fetch(days: int):
    symbol = config.SYMBOL_GOLD
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    print(f"Fetching {symbol} history ({days}d) from MT5 -> data/backtest/ ...")
    for tf in TIMEFRAMES:
        try:
            df = data_loader.fetch_from_mt5(
                symbol, tf, start, end,
                login=config.MT5_LOGIN, password=config.MT5_PASSWORD,
                server=config.MT5_SERVER,
            )
            print(f"  {tf}: {len(df)} candles cached")
        except Exception as e:
            print(f"  {tf}: FETCH FAILED - {e}")


def do_run(confidence_gate: bool):
    symbol = config.SYMBOL_GOLD
    frames = {}
    for tf in TIMEFRAMES:
        try:
            frames[tf] = data_loader.load(symbol, tf)
        except FileNotFoundError as e:
            print(f"[skip] {e}")
    if "M15" not in frames or "M5" not in frames:
        print("ERROR: M15 + M5 cached data required. Run with --fetch first.")
        return

    point = 0.001
    print(f"\nRunning Gold backtest - gate={'ON' if confidence_gate else 'OFF'} "
          f"(MIN_CONFIDENCE={config.MIN_CONFIDENCE}) ...")
    bt = GoldBacktest(symbol, frames, point=point, confidence_gate=confidence_gate)
    stats = bt.run()

    print("\n" + "=" * 60)
    print(f"  BACKTEST RESULTS - {symbol}")
    print("=" * 60)
    print(stats.summary())
    print("=" * 60)

    if bt.trades:
        print("\nLast 10 trades:")
        for t in bt.trades[-10:]:
            print(f"  {str(t.entry_time)[:16]}  {t.direction:4s}  "
                  f"entry {t.entry:.2f}  exit {t.exit:.2f}  "
                  f"{t.exit_reason:9s}  {t.r_multiple:+.2f}R  conf {t.confidence:.0f}%")


def main():
    ap = argparse.ArgumentParser(description="GoldBot backtester")
    ap.add_argument("--fetch", action="store_true", help="Fetch+cache history from MT5")
    ap.add_argument("--run", action="store_true", help="Run backtest on cached data")
    ap.add_argument("--days", type=int, default=60, help="History window for --fetch")
    ap.add_argument("--no-gate", action="store_true", help="Disable confidence gate")
    args = ap.parse_args()

    if args.fetch:
        do_fetch(args.days)
    if args.run:
        do_run(confidence_gate=not args.no_gate)
    if not args.fetch and not args.run:
        ap.print_help()


if __name__ == "__main__":
    main()
