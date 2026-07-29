# ============================================================
#  backtesting/tests/test_simulator.py
#  Simulator + metrics ki math correctness verify karta hai.
#  Run: python -m backtesting.tests.test_simulator
# ============================================================

import sys, os, types

# Stub config (no MT5 needed) BEFORE importing simulator
_cfg = types.ModuleType("config")
_cfg.PARTIAL_CLOSE_RR = 1.0
_cfg.PARTIAL_CLOSE_PCT = 0.70
sys.modules.setdefault("config", _cfg)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backtesting.simulator import SimTrade, simulate_trade
from backtesting import metrics


def _bar(h, l, c, t=0):
    return {"high": h, "low": l, "close": c, "time": t}


def _approx(a, b, tol=1e-6):
    return abs(a - b) <= tol


def test_clean_tp_hit():
    # BUY entry 100, SL 90 (risk 10), TP 130 (3R). Price rallies straight to TP.
    tr = SimTrade("BUY", 100, 90, 130, 0.01, entry_time=0)
    bars = [_bar(105, 99, 104, 1), _bar(135, 103, 132, 2)]
    simulate_trade(tr, bars)
    # partial 70% booked at 1R (bar1 fav_r=0.5 no; bar2 hi=135 => partial then TP)
    # realized = 1.0*0.7 = 0.7 ; remaining 0.3 exits at TP (3R) => 0.9 ; total 1.6
    assert tr.exit_reason == "TP", tr.exit_reason
    assert _approx(tr.r_multiple, 0.7 + 3.0 * 0.3), tr.r_multiple
    print("test_clean_tp_hit OK  r=%.3f" % tr.r_multiple)


def test_clean_sl_hit():
    # BUY entry 100 SL 90 TP 130. Price drops straight to SL, never went +1R.
    tr = SimTrade("BUY", 100, 90, 130, 0.01, entry_time=0)
    bars = [_bar(101, 95, 96, 1), _bar(97, 89, 90, 2)]
    simulate_trade(tr, bars)
    assert tr.exit_reason == "SL", tr.exit_reason
    assert _approx(tr.r_multiple, -1.0), tr.r_multiple
    print("test_clean_sl_hit OK  r=%.3f" % tr.r_multiple)


def test_breakeven_after_1r():
    # BUY 100 SL 90 TP 130. Goes to +1R (110) -> partial+BE, then reverses to entry.
    tr = SimTrade("BUY", 100, 90, 130, 0.01, entry_time=0)
    bars = [_bar(111, 99, 110, 1),   # fav_r=1.1 -> partial 0.7R booked, SL->BE(100)
            _bar(101, 99, 100, 2)]   # hits BE (100) -> exit
    simulate_trade(tr, bars)
    # realized 0.7R from partial; remaining 0.3 exits at BE (0R). total 0.7R
    assert tr.exit_reason in ("BE", "SL"), tr.exit_reason
    assert _approx(tr.r_multiple, 0.7), tr.r_multiple
    print("test_breakeven_after_1r OK  r=%.3f reason=%s" % (tr.r_multiple, tr.exit_reason))


def test_sell_tp():
    # SELL 100 SL 110 (risk10) TP 70 (3R). Drops to TP.
    tr = SimTrade("SELL", 100, 110, 70, 0.01, entry_time=0)
    bars = [_bar(101, 88, 90, 1), _bar(95, 68, 70, 2)]
    simulate_trade(tr, bars)
    assert tr.exit_reason == "TP", tr.exit_reason
    assert _approx(tr.r_multiple, 0.7 + 3.0 * 0.3), tr.r_multiple
    print("test_sell_tp OK  r=%.3f" % tr.r_multiple)


def test_conservative_sl_priority():
    # Both SL and TP inside same bar → SL must win (conservative).
    tr = SimTrade("BUY", 100, 90, 130, 0.01, entry_time=0)
    bars = [_bar(135, 85, 100, 1)]   # touches both TP(130) and SL(90)
    simulate_trade(tr, bars)
    assert tr.exit_reason == "SL", tr.exit_reason
    print("test_conservative_sl_priority OK  reason=%s" % tr.exit_reason)


def test_metrics():
    # Build synthetic R outcomes: +2, -1, +3, -1, -1
    trades = []
    for r in (2.0, -1.0, 3.0, -1.0, -1.0):
        t = SimTrade("BUY", 100, 90, 130, 0.01, entry_time=0)
        t.r_multiple = r
        trades.append(t)
    s = metrics.compute(trades)
    assert s.trades == 5
    assert s.wins == 2 and s.losses == 3
    assert _approx(s.total_r, 2.0), s.total_r
    assert s.max_consecutive_losses == 2, s.max_consecutive_losses
    # profit factor = (2+3)/(1+1+1)=5/3
    assert _approx(s.profit_factor, 5.0 / 3.0), s.profit_factor
    # max drawdown: equity path 2,1,4,3,2 -> peak4 -> dd=2
    assert _approx(s.max_drawdown_r, 2.0), s.max_drawdown_r
    print("test_metrics OK  " + s.summary().replace("\n", " | "))


if __name__ == "__main__":
    test_clean_tp_hit()
    test_clean_sl_hit()
    test_breakeven_after_1r()
    test_sell_tp()
    test_conservative_sl_priority()
    test_metrics()
    print("\nALL SIMULATOR TESTS PASSED")
