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

    _TF_MINS = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}

    def __init__(self, symbol, frames, point=0.001,
                 confidence_gate=True, warmup_m15=120, strategy_fn=None,
                 step_tf="M15", fill_tf="M5", freeze_extra=None):
        self.symbol = symbol
        self.frames = frames
        self.point = point
        self.confidence_gate = confidence_gate
        self.warmup = warmup_m15
        self.strategy_fn = strategy_fn   # None → live gold_hybrid (testing seam)
        # Decision cadence (step_tf) aur fill granularity (fill_tf).
        # Swing/hybrid: step M15, fill M5. Scalper: step M5, fill M1.
        self.step_tf = step_tf
        self.fill_tf = fill_tf
        self.freeze_extra = freeze_extra or []   # scalper modules to clock-freeze
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

    def _future_fill(self, t, cap=None):
        """
        Entry ke baad ke fill_tf bars. `cap` set ho to sirf utne bars
        (time-stop ke hisaab se trade kabhi utna hold nahi karti, is
        liye baaki bars bekaar — yeh M1 fills pe bara speed-up hai).
        """
        fdf = self.frames[self.fill_tf]
        fut = fdf[fdf["time"] > t]
        if cap is not None:
            fut = fut.head(cap)
        return fut.to_dict("records")

    def run(self):
        import ai.confidence as ai_conf
        from sessions import kill_zones

        self._isolate()
        # Modules jinka clock freeze karna hai (jinme `from datetime import datetime`)
        freeze_modules = [self._gh, kill_zones] + list(self.freeze_extra)
        try:
            from strategies import silver_bullet as _sb
            freeze_modules.append(_sb)
        except Exception:
            pass

        step_df = self.frames[self.step_tf]
        n = len(step_df)
        open_until = None   # trade band hone tak ka time — overlap avoid
        fill_mins = self._TF_MINS.get(self.fill_tf, 5)

        try:
            for i in range(self.warmup, n):
                t = step_df.iloc[i]["time"]

                if open_until is not None and t <= open_until:
                    continue   # abhi ek trade chal rahi hai

                sliced = {tf: _slice_upto(df, t) for tf, df in self.frames.items()}
                if len(sliced.get("M5", [])) < 10:
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
                # Live config ka time-stop reflect karo (fill_tf bars = mins/fill_mins)
                import config as _cfg
                mh = getattr(_cfg, "MAX_HOLD_MINUTES", 0)
                max_hold = int(mh / fill_mins) if mh else None
                # Time-stop hai to sirf utne (+margin) fill bars chahiye — speed-up
                cap = (max_hold + 5) if max_hold else None
                future = self._future_fill(t, cap=cap)
                if not future:
                    break
                simulate_trade(tr, future, max_hold_bars=max_hold)
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
