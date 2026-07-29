# ============================================================
#  backtesting/simulator.py — Trade fill + management simulator
# ============================================================
#
#  Yeh backtester ka DIL hai — deterministic aur pure (no MT5,
#  no clock, no I/O). Ek trade ko entry se exit tak bar-by-bar
#  simulate karta hai, live trade_manager.py ke rules ke mutabiq:
#    * Partial close @ config.PARTIAL_CLOSE_RR (default 1:1, 70%)
#    * Break-even @ 1R
#    * SL → TP1 trail @ 2R
#    * SL / TP hit detection (intrabar, conservative)
#
#  Conservative intrabar rule: agar ek hi bar mein SL aur TP dono
#  touch hote hon (ambiguous), hum SL ko pehle maante hain (worst
#  case) — taake backtest optimistic na ho. Yeh institutional
#  backtesting standard hai.
# ============================================================

from dataclasses import dataclass, field
import config


@dataclass
class SimTrade:
    direction: str          # "BUY" | "SELL"
    entry: float
    sl: float
    tp: float               # final TP (tp3)
    lot: float
    entry_time: object
    comment: str = ""
    confidence: float = 0.0

    # filled during simulation
    exit: float = None
    exit_time: object = None
    exit_reason: str = ""   # TP | SL | BE | TP1_TRAIL | EOD
    r_multiple: float = 0.0
    partial_done: bool = False
    realized_r: float = 0.0     # R booked from partial closes
    remaining: float = 1.0      # fraction of position still open

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def is_buy(self) -> bool:
        return self.direction == "BUY"


def _hit(price_low, price_high, level, is_buy_stop_side) -> bool:
    """Kya `level` is bar ke range [low, high] mein touch hua?"""
    return price_low <= level <= price_high


def simulate_trade(trade: SimTrade, future_bars, max_hold_bars=None) -> SimTrade:
    """
    trade:          open SimTrade (entry already set)
    future_bars:    iterable of dict/rows with high/low/close/time,
                    entry ke BAAD ke bars (chronological).
    max_hold_bars:  None → no time limit. Warna itne bars ke baad
                    trade force-close (scalp behavior — ghanton tak
                    hold nahi). Bars usi granularity ke hain jis par
                    fills simulate ho rahe hain (M5).

    Live trade_manager rules ko replicate karta hai. Mutates &
    returns trade with exit fields set.
    """
    risk = trade.risk_per_unit
    if risk <= 0:
        trade.exit = trade.entry
        trade.exit_reason = "INVALID"
        return trade

    is_buy = trade.is_buy
    sl = trade.sl
    tp = trade.tp
    entry = trade.entry

    partial_rr  = config.PARTIAL_CLOSE_RR
    partial_pct = config.PARTIAL_CLOSE_PCT
    if not getattr(config, "PARTIAL_CLOSE_ENABLED", True):
        partial_pct = 0.0
    moved_be = False
    moved_tp1 = False

    for bar_i, bar in enumerate(future_bars):
        hi, lo = bar["high"], bar["low"]
        t = bar["time"]

        # Best favorable price this bar → favorable excursion in R.
        best_price = hi if is_buy else lo
        fav_r = ((best_price - entry) if is_buy else (entry - best_price)) / risk

        sl_touched = (lo <= sl <= hi)
        tp_touched = (lo <= tp <= hi)

        # ── 1. SL check first (conservative: SL priority if both touch) ──
        #    SL valid at bar START is used; trailing updates apply to NEXT bar.
        if sl_touched:
            exit_r = ((sl - entry) / risk) if is_buy else ((entry - sl) / risk)
            trade.exit = sl
            trade.exit_time = t
            trade.exit_reason = "BE" if moved_be and abs(sl - entry) < 1e-9 else \
                                ("TP1_TRAIL" if moved_tp1 else "SL")
            trade.r_multiple = trade.realized_r + exit_r * trade.remaining
            return trade

        # ── 2. Partial close @ partial_rr (books BEFORE TP within a bar) ──
        if not trade.partial_done and fav_r >= partial_rr:
            trade.realized_r += partial_rr * partial_pct
            trade.remaining -= partial_pct
            trade.partial_done = True

        # ── 3. TP check on remaining position ──
        if tp_touched:
            exit_r = ((tp - entry) / risk) if is_buy else ((entry - tp) / risk)
            trade.exit = tp
            trade.exit_time = t
            trade.exit_reason = "TP"
            trade.r_multiple = trade.realized_r + exit_r * trade.remaining
            return trade

        # ── 4. Trailing SL logic (mirror trade_manager._manage_trade) ──
        if fav_r >= 2.0 and not moved_tp1:
            sl = entry + risk if is_buy else entry - risk   # SL → TP1 (entry + 1R)
            moved_tp1 = True
            moved_be = True
        elif fav_r >= 1.0 and not moved_be:
            sl = entry            # break-even
            moved_be = True

        # ── 5. Time-based exit (scalp) — max hold cross ho gaya ──
        if max_hold_bars is not None and (bar_i + 1) >= max_hold_bars:
            close = bar["close"]
            exit_r = ((close - entry) / risk) if is_buy else ((entry - close) / risk)
            trade.exit = close
            trade.exit_time = t
            trade.exit_reason = "TIME"
            trade.r_multiple = trade.realized_r + exit_r * trade.remaining
            return trade

    # ── Ran out of bars — close at last bar close (EOD/data end) ──
    if future_bars:
        last = future_bars[-1]
        exit_price = last["close"]
        exit_r = ((exit_price - entry) / risk) if is_buy else ((entry - exit_price) / risk)
        trade.exit = exit_price
        trade.exit_time = last["time"]
        trade.exit_reason = "EOD"
        trade.r_multiple = trade.realized_r + exit_r * trade.remaining
    return trade
