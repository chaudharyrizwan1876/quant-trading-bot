# ============================================================
#  backtesting/engine.py — Bar-replay backtest runner (Gold)
# ============================================================
#
#  DESIGN / ASSUMPTIONS (honest disclosure — taake results
#  correctly interpret hon, tick-perfect samajh kar nahi):
#
#   * Decision clock = M15 bar closes (Gold ka primary entry TF).
#     Har M15 close par strategy ko call karte hain.
#   * No-lookahead: har TF frame sirf un candles tak sliced hoti
#     hai jinka time <= current M15 close. HTF candle ko "closed-
#     at-appearance" treat kiya jata hai (standard approximation).
#   * Fills M5 granularity par simulate hote hain (simulator.py),
#     conservative intrabar SL-priority ke saath.
#   * Ek waqt mein ek hi position (live can_open_trade bhi single
#     position enforce karta hai Gold ke liye).
#   * Risk-cap / lot sizing SKIP — woh sirf SL/TP ko proportionally
#     scale karta hai (RR unchanged), is liye R-multiple stats par
#     koi asar nahi. Position sizing alag concern hai.
#   * Side effects (logs, weekly-quota file, trade_memory) isolate/
#     neutralize kiye jate hain taake live data corrupt na ho aur
#     backtest historical-neutral rahe.
# ============================================================

import os
import tempfile
import importlib
import pandas as pd

from backtesting.clock import frozen_time
from backtesting.simulator import SimTrade, simulate_trade
from backtesting import metrics


def _slice_upto(df: pd.DataFrame, t) -> pd.DataFrame:
    """Sirf woh candles jinka time <= t (no lookahead)."""
    return df[df["time"] <= t]


class GoldBacktest:
    """
    Gold hybrid strategy ka bar-replay backtest.
    frames: {"D1":df,"H1":df,"M30":df,"M15":df,"M5":df,"M1":df}
            (time column datetime64 UTC). M15 + M5 zaroori hain.
    """

    def __init__(self, symbol, frames, point=0.001,
                 confidence_gate=True, warmup_m15=120, strategy_fn=None):
        self.symbol = symbol
        self.frames = frames
        self.point = point
        self.confidence_gate = confidence_gate
        self.warmup = warmup_m15
        self.strategy_fn = strategy_fn   # None → live gold_hybrid (testing seam)
        self.trades = []

    # ── side-effect isolation ──
    def _isolate(self):
        """Live files/memory ko backtest se bachao."""
        import config
        tmp = tempfile.mkdtemp(prefix="gold_bt_")
        self._saved = {
            "LOGS_FILE": config.LOGS_FILE,
            "TRADES_FILE": config.TRADES_FILE,
            "LOG_TO_CONSOLE": getattr(config, "LOG_TO_CONSOLE", True),
        }
        config.LOGS_FILE = os.path.join(tmp, "bt_logs.csv")
        config.TRADES_FILE = os.path.join(tmp, "bt_trades.csv")
        config.LOG_TO_CONSOLE = False   # backtest console quiet

        from strategies import gold_hybrid
        self._gh = gold_hybrid
        self._saved_weekly = gold_hybrid.WEEKLY_FILE
        gold_hybrid.WEEKLY_FILE = os.path.join(tmp, "bt_weekly.json")

        from memory import trade_memory
        self._tm = trade_memory
        self._saved_mem = trade_memory.MEMORY_FILE
        trade_memory.MEMORY_FILE = os.path.join(tmp, "bt_memory.json")
        trade_memory._memory = {"combos": {}, "symbols": {}, "hours": {}}

    def _restore(self):
        import config
        config.LOGS_FILE = self._saved["LOGS_FILE"]
        config.TRADES_FILE = self._saved["TRADES_FILE"]
        config.LOG_TO_CONSOLE = self._saved["LOG_TO_CONSOLE"]
        self._gh.WEEKLY_FILE = self._saved_weekly
        self._tm.MEMORY_FILE = self._saved_mem
        self._tm._memory = None

    def _future_m5(self, t):
        m5 = self.frames["M5"]
        fut = m5[m5["time"] > t]
        return [dict(r) for _, r in fut.iterrows()]

    def run(self):
        import ai.confidence as ai_conf
        from sessions import kill_zones

        self._isolate()
        # Modules jinka clock freeze karna hai (jinme `from datetime import datetime`)
        freeze_modules = [self._gh, kill_zones]
        try:
            from strategies import silver_bullet as _sb
            freeze_modules.append(_sb)
        except Exception:
            pass

        m15 = self.frames["M15"]
        n = len(m15)
        open_until = None   # trade band hone tak ka time — overlap avoid

        try:
            for i in range(self.warmup, n):
                row = m15.iloc[i]
                t = row["time"]

                if open_until is not None and t <= open_until:
                    continue   # abhi ek trade chal rahi hai

                sliced = {tf: _slice_upto(df, t) for tf, df in self.frames.items()}
                if len(sliced.get("M15", [])) < 40 or len(sliced.get("M5", [])) < 10:
                    continue

                strat = self.strategy_fn or self._gh.generate_gold_signal
                with frozen_time(t.to_pydatetime(), freeze_modules):
                    try:
                        result = strat(
                            df_h1=sliced.get("H1"), df_m30=sliced.get("M30"),
                            df_m15=sliced.get("M15"), df_m5=sliced.get("M5"),
                            df_m1=sliced.get("M1"), point=self.point,
                            df_d1=sliced.get("D1"), news_sig=None,
                        )
                    except Exception:
                        continue

                if not result or result.get("signal") not in ("BUY", "SELL"):
                    continue

                # Confidence gate (same as live)
                rr = self._rr(result)
                conf = ai_conf.evaluate(result.get("factors", {}), rr=rr, memory_adj=0)
                if self.confidence_gate and not conf.passed:
                    continue

                tr = SimTrade(
                    direction=result["signal"],
                    entry=result["entry"], sl=result["sl"],
                    tp=result.get("tp3") or result.get("tp1"),
                    lot=result.get("lot", 0.01), entry_time=t,
                    comment=result.get("comment", ""), confidence=conf.confidence,
                )
                future = self._future_m5(t)
                if not future:
                    break
                simulate_trade(tr, future)
                self.trades.append(tr)
                open_until = tr.exit_time
        finally:
            self._restore()

        return metrics.compute(self.trades)

    @staticmethod
    def _rr(result):
        entry = result.get("entry", 0); sl = result.get("sl", 0)
        tp = result.get("tp3") or result.get("tp1") or 0
        if entry <= 0 or sl <= 0 or tp <= 0:
            return 0.0
        d = abs(entry - sl)
        return abs(entry - tp) / d if d > 0 else 0.0
