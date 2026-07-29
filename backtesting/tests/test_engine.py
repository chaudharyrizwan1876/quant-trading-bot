# ============================================================
#  backtesting/tests/test_engine.py
#  Replay harness (slicing + frozen clock + fill sim + stats)
#  ko ek deterministic injected strategy se end-to-end verify
#  karta hai, aur real gold_hybrid ke saath smoke-run karta hai.
#  Run: python -m backtesting.tests.test_engine
# ============================================================

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from datetime import datetime, timezone, timedelta

from backtesting.engine import GoldBacktest


def _make_frames(n_m15=300, start_price=3300.0):
    """Simple upward-drifting synthetic OHLCV for each timeframe."""
    base = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # Monday
    frames = {}

    def build(count, minutes, drift):
        rows = []
        p = start_price
        for i in range(count):
            t = base + timedelta(minutes=minutes * i)
            o = p
            c = p + drift
            h = max(o, c) + 1.0
            l = min(o, c) - 1.0
            rows.append({"time": t, "open": o, "high": h, "low": l,
                         "close": c, "tick_volume": 100 + (i % 5) * 10})
            p = c
        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    frames["D1"]  = build(max(30, n_m15 // 96), 1440, 5.0)
    frames["H1"]  = build(max(50, n_m15 // 4), 60, 1.5)
    frames["M30"] = build(max(100, n_m15 // 2), 30, 0.8)
    frames["M15"] = build(n_m15, 15, 0.5)
    frames["M5"]  = build(n_m15 * 3, 5, 0.15)
    frames["M1"]  = build(n_m15 * 15, 1, 0.03)
    return frames


def test_injected_strategy_produces_trade():
    frames = _make_frames()
    m15 = frames["M15"]
    fire_time = m15.iloc[150]["time"]
    fired = {"count": 0}

    def stub_strategy(df_m15=None, df_m5=None, **kw):
        # Fire exactly once, at the target bar
        cur_t = df_m15.iloc[-1]["time"]
        if cur_t == fire_time and fired["count"] == 0:
            fired["count"] += 1
            entry = df_m15.iloc[-1]["close"]
            return {
                "signal": "BUY", "entry": entry,
                "sl": entry - 10.0, "tp3": entry + 30.0, "tp1": entry + 10.0,
                "comment": "TEST_BUY", "score": 15,
                "factors": {"htf_trend_aligned": True, "institutional_sweep": True,
                            "m5_confirmation": True, "prime_session": True,
                            "volume_confirmation": True, "m15_structure_aligned": True},
            }
        return {"signal": "NO_TRADE"}

    bt = GoldBacktest("XAUUSDm", frames, confidence_gate=True,
                      warmup_m15=50, strategy_fn=stub_strategy)
    stats = bt.run()
    assert stats.trades == 1, f"expected 1 trade, got {stats.trades}"
    tr = bt.trades[0]
    assert tr.direction == "BUY"
    assert tr.exit_reason in ("TP", "BE", "SL", "TP1_TRAIL", "EOD"), tr.exit_reason
    print(f"test_injected_strategy_produces_trade OK — "
          f"exit={tr.exit_reason} r={tr.r_multiple:+.2f} conf={tr.confidence:.0f}%")
    print("   " + stats.summary().replace("\n", " | "))


def test_confidence_gate_blocks_low():
    frames = _make_frames()
    m15 = frames["M15"]
    fire_time = m15.iloc[150]["time"]

    def weak_strategy(df_m15=None, **kw):
        if df_m15.iloc[-1]["time"] == fire_time:
            entry = df_m15.iloc[-1]["close"]
            return {"signal": "BUY", "entry": entry, "sl": entry - 10,
                    "tp3": entry + 20, "tp1": entry + 10, "comment": "WEAK",
                    "factors": {"order_block": True}}  # ~ low confidence
        return {"signal": "NO_TRADE"}

    bt = GoldBacktest("XAUUSDm", frames, confidence_gate=True,
                      warmup_m15=50, strategy_fn=weak_strategy)
    stats = bt.run()
    assert stats.trades == 0, f"weak setup should be gated, got {stats.trades}"
    print("test_confidence_gate_blocks_low OK — weak setup correctly filtered")


def test_real_gold_hybrid_smoke():
    """Real strategy over synthetic data — must complete without exception."""
    frames = _make_frames(n_m15=250)
    bt = GoldBacktest("XAUUSDm", frames, confidence_gate=True, warmup_m15=60)
    stats = bt.run()
    assert stats.trades >= 0
    print(f"test_real_gold_hybrid_smoke OK — completed, {stats.trades} trades on synthetic data")


if __name__ == "__main__":
    test_injected_strategy_produces_trade()
    test_confidence_gate_blocks_low()
    test_real_gold_hybrid_smoke()
    print("\nALL ENGINE TESTS PASSED")
