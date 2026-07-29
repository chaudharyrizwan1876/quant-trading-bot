# ============================================================
#  risk_manager.py — V8.4
#  NEW: calculate_lot_and_sl() — SL ko 1% risk ke hisaab se
#  HARD CAP karta hai. Agar minimum lot size par bhi SL 1%
#  se zyada risk banaye, to SL DISTANCE khud chota kar diya
#  jata hai (lot minimum rehta hai) — matlab risk kabhi
#  1% se zyada nahi jata, chahe ATR kuch bhi kahe.
# ============================================================

import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import config
from logger import log_event

_daily_sl_count   = {}
_sl_track_date    = None
_day_start_equity = None

# ── Consecutive-loss circuit breaker state ──
# Yeh trade_memory ke win-rate blocking se ALAG hai: woh pattern/
# symbol ki historical quality dekhta hai (slow), yeh ek turant
# "streak" breaker hai — lagataar N losses ke baad thoda cooldown,
# taake ek bure market phase mein bot revenge-trade na kare.
_consecutive_losses = 0
_breaker_until      = None   # datetime tak trading paused


def _reset_daily_if_needed():
    global _daily_sl_count, _sl_track_date, _day_start_equity
    today = datetime.now(timezone.utc).date()
    if _sl_track_date != today:
        _daily_sl_count = {}
        _sl_track_date  = today
        acc = mt5.account_info()
        if acc:
            _day_start_equity = acc.equity
            log_event("INFO", f"New trading day — Starting equity: ${_day_start_equity:.2f}")


def record_sl_hit(symbol: str):
    _reset_daily_if_needed()
    _daily_sl_count[symbol] = _daily_sl_count.get(symbol, 0) + 1
    log_event("INFO", f"[{symbol}] SL hit — Today: {_daily_sl_count[symbol]}")


def record_trade_result(symbol: str, profit: float, was_sl: bool):
    """
    Har closed trade (win ya loss) ke baad call hota hai —
    consecutive-loss streak track karta hai. Loss pe streak++,
    win pe reset. Threshold cross ho to cooldown-based breaker on.
    """
    global _consecutive_losses, _breaker_until
    is_loss = was_sl or profit < 0
    if is_loss:
        _consecutive_losses += 1
        limit = getattr(config, "MAX_CONSECUTIVE_LOSSES", 3)
        if _consecutive_losses >= limit:
            mins = getattr(config, "CONSECUTIVE_LOSS_COOLDOWN_MINS", 120)
            _breaker_until = datetime.now(timezone.utc) + timedelta(minutes=mins)
            log_event("WARNING",
                f"CIRCUIT BREAKER — {_consecutive_losses} consecutive losses. "
                f"Trading paused {mins}min (until {_breaker_until.isoformat()})."
            )
    else:
        if _consecutive_losses > 0:
            log_event("INFO", f"Win — consecutive-loss streak reset (was {_consecutive_losses}).")
        _consecutive_losses = 0
        _breaker_until = None


def consecutive_losses() -> int:
    return _consecutive_losses


def is_circuit_breaker_active() -> bool:
    global _breaker_until, _consecutive_losses
    if _breaker_until is None:
        return False
    if datetime.now(timezone.utc) >= _breaker_until:
        log_event("INFO", "Circuit breaker cooldown over — trading resumed.")
        _breaker_until = None
        _consecutive_losses = 0
        return False
    return True


def get_daily_sl_count(symbol: str) -> int:
    _reset_daily_if_needed()
    return _daily_sl_count.get(symbol, 0)


def is_daily_loss_limit_hit() -> bool:
    _reset_daily_if_needed()
    if _day_start_equity is None or _day_start_equity <= 0:
        return False
    acc = mt5.account_info()
    if acc is None: return False
    loss_pct = (_day_start_equity - acc.equity) / _day_start_equity
    if loss_pct >= config.MAX_DAILY_LOSS_PCT:
        log_event("WARNING",
            f"DAILY LOSS LIMIT HIT! Start:${_day_start_equity:.2f} "
            f"Now:${acc.equity:.2f} Loss:{loss_pct*100:.1f}%"
        )
        return True
    return False


def is_spread_acceptable(symbol: str) -> bool:
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None or info is None:
        return True

    spread_price = tick.ask - tick.bid

    if "XAU" in symbol.upper():
        max_spread_dollar = config.MAX_SPREAD_GOLD_DOLLAR
        if spread_price > max_spread_dollar:
            log_event("INFO",
                f"[{symbol}] Spread ${spread_price:.2f} > "
                f"max ${max_spread_dollar:.2f} — Skip."
            )
            return False
        return True

    spread_pips = spread_price / info.point / 10
    max_spread  = config.MAX_SPREAD_FOREX_PIPS
    if spread_pips > max_spread:
        return False
    return True


# ─────────────────────────────────────────────
#  V8.4: SL-CAPPING LOT CALCULATOR
#
#  Poora naya approach — pehle jaisa "calculate lot from SL"
#  nahi, ab dono ek saath solve hote hain taake risk KABHI
#  1% se zyada na jaye:
#
#  1. Pehle dekho: min_lot pe risk_amount ke hisaab se
#     max allowed SL distance kya banti hai
#  2. Agar strategy ki di hui SL us max se choti hai →
#     normal lot calculate karo (jaisa pehle tha)
#  3. Agar strategy ki di hui SL us max se BARI hai →
#     SL ko us max distance tak SHRINK kar do, lot = min_lot
#     (TP proportionally scale hoga caller mein, RR same rahega)
# ─────────────────────────────────────────────

def risk_fraction_for_confidence(confidence: float) -> float:
    """
    Confidence-scaled position sizing. Higher-conviction setup =
    zyada risk (full RISK_PERCENT tak); minimum-threshold ke paas
    wale setups = kam risk (RISK_PERCENT_MIN). Linear scale
    [MIN_CONFIDENCE .. 100] → [RISK_PERCENT_MIN .. RISK_PERCENT].
    Kabhi RISK_PERCENT (1% hard cap) se upar nahi jata.
    """
    r_max = config.RISK_PERCENT
    r_min = getattr(config, "RISK_PERCENT_MIN", r_max)
    if r_min >= r_max:
        return r_max
    lo = getattr(config, "MIN_CONFIDENCE", 66.0)
    hi = 100.0
    c = max(lo, min(confidence, hi))
    frac = (c - lo) / (hi - lo) if hi > lo else 1.0
    return r_min + frac * (r_max - r_min)


def calculate_lot_and_sl(symbol: str, sl_price: float, entry_price: float,
                         is_buy: bool, risk_pct: float = None) -> dict:
    """
    risk_pct: None → config.RISK_PERCENT (default 1%). Confidence-scaled
              sizing ke liye caller yahan chota fraction pass kar sakta hai.
    Return: {
        "lot":        float,
        "sl_price":   float,   # ORIGINAL ya CAPPED
        "was_capped": bool,
        "sl_distance": float
    }
    """
    fallback = {
        "lot": config.LOT_SIZE_GOLD, "sl_price": sl_price,
        "was_capped": False, "sl_distance": abs(entry_price - sl_price)
    }

    try:
        acc = mt5.account_info()
        if acc is None:
            log_event("WARNING", f"[{symbol}] Account info nahi — fallback lot.")
            return fallback

        equity      = acc.equity
        risk_pct    = config.RISK_PERCENT if risk_pct is None else min(risk_pct, config.RISK_PERCENT)
        risk_amount = equity * risk_pct

        info = mt5.symbol_info(symbol)
        if info is None:
            return fallback

        min_lot, max_lot = info.volume_min, info.volume_max
        lot_step = info.volume_step or 0.01

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return fallback

        tick_val, tick_size = info.trade_tick_value, info.trade_tick_size
        if tick_val <= 0 or tick_size <= 0:
            return fallback

        # $ risk per 1 lot per $1 price move
        dollar_per_unit_per_lot = tick_val / tick_size

        # Ideal lot jo poori sl_distance pe risk_amount de
        sl_dollar_at_this_distance_per_lot = sl_distance * dollar_per_unit_per_lot
        ideal_lot = risk_amount / sl_dollar_at_this_distance_per_lot

        if ideal_lot >= min_lot:
            # Normal case — SL theek hai, lot round karo
            lot = round(round(ideal_lot / lot_step) * lot_step, 2)
            lot = max(min_lot, min(lot, max_lot))
            lot = max(lot, config.MIN_LOT_SIZE)

            log_event("INFO",
                f"[{symbol}] Lot:{lot} | Equity:${equity:.0f} "
                f"Risk:${risk_amount:.2f}({risk_pct*100:.1f}%) "
                f"SL_dist:{sl_distance:.5f} (no cap needed)"
            )
            return {
                "lot": lot, "sl_price": sl_price,
                "was_capped": False, "sl_distance": sl_distance
            }

        # ── SL CAP NEEDED ──
        # Minimum lot pe bhi risk 1% se zyada — SL distance ko
        # shrink karo taake min_lot * new_sl_dollar = risk_amount
        max_sl_dollar_per_lot = risk_amount / min_lot
        max_sl_distance = max_sl_dollar_per_lot / dollar_per_unit_per_lot

        new_sl_price = (entry_price - max_sl_distance) if is_buy \
                       else (entry_price + max_sl_distance)
        new_sl_price = round(new_sl_price, info.digits)

        log_event("INFO",
            f"[{symbol}] SL CAPPED! Original SL_dist:{sl_distance:.5f} "
            f"(risk too high even at min_lot) → "
            f"New SL_dist:{max_sl_distance:.5f} @ min_lot:{min_lot} "
            f"— Risk exactly {risk_pct*100:.1f}%"
        )

        return {
            "lot": min_lot, "sl_price": new_sl_price,
            "was_capped": True, "sl_distance": max_sl_distance
        }

    except Exception as e:
        log_event("ERROR", f"[{symbol}] Lot/SL calc error: {e}")
        return fallback


def calculate_lot(symbol: str, sl_price: float, entry_price: float) -> float:
    """Backward-compat wrapper — sirf lot chahiye ho to."""
    result = calculate_lot_and_sl(symbol, sl_price, entry_price, is_buy=True)
    return result["lot"]


def can_open_trade(symbol: str) -> bool:
    if is_daily_loss_limit_hit():
        return False

    # Consecutive-loss circuit breaker (streak-based cooldown)
    if is_circuit_breaker_active():
        log_event("INFO", f"[{symbol}] Circuit breaker active — Skip.")
        return False

    positions = mt5.positions_get() or []

    # Global exposure guard — total open positions ka hard cap
    max_open = getattr(config, "MAX_OPEN_TRADES", 3)
    if len(positions) >= max_open:
        log_event("INFO",
            f"[{symbol}] Max open trades ({max_open}) reached — Skip.")
        return False

    sym_pos = [p for p in positions if p.symbol == symbol]
    if sym_pos:
        log_event("INFO", f"[{symbol}] Already open — Skip.")
        return False

    if not is_spread_acceptable(symbol):
        return False

    try:
        from memory import trade_memory as tm
        if tm.is_symbol_blocked(symbol):
            return False
    except Exception:
        pass

    return True


def get_open_trade_count() -> int:
    positions = mt5.positions_get()
    return len(positions) if positions else 0


def score_signal(symbol: str, result: dict) -> float:
    if result.get("signal") == "NO_TRADE":
        return 0.0
    score = 0.0
    if "XAU" in symbol.upper():
        score += 50
    entry = result.get("entry", 0)
    sl    = result.get("sl", 0)
    tp    = result.get("tp3") or result.get("tp1", 0)
    if entry > 0 and sl > 0 and tp > 0:
        sl_size = abs(entry - sl)
        tp_size = abs(entry - tp)
        if sl_size > 0:
            score += (tp_size / sl_size) * 10
    comment = result.get("comment","").upper()
    if "NEWS" in comment: score += 20
    if "OB"   in comment: score += 15
    if "FVG"  in comment: score += 10
    if "LIQ"  in comment: score += 5
    if "BREAKER" in comment: score += 8
    strat_score = result.get("score", 0)
    score += strat_score * 2
    return score
