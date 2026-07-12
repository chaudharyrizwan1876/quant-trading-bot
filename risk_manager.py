# ============================================================
#  risk_manager.py — V7.2
#  FIX: Correlation filter ab direction-aware hai
#  Same direction (same side) = Allow
#  Opposite direction (conflicting) = Skip
# ============================================================

import MetaTrader5 as mt5
from datetime import datetime, timezone
import config
from logger import log_event

_daily_sl_count   = {}
_sl_track_date    = None
_day_start_equity = None


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
        log_event("INFO",
            f"[{symbol}] Spread {spread_pips:.1f} pips > "
            f"max {max_spread} — Skip."
        )
        return False
    return True


# ─────────────────────────────────────────────
#  FIX: DIRECTION-AWARE CORRELATION FILTER
#
#  Same group + same direction (BUY+BUY ya SELL+SELL)
#    = Allow (correlated pairs same taraf ja rahe hain)
#  Same group + opposite direction (BUY vs SELL)
#    = Skip (conflicting signal — noise ho sakta hai)
# ─────────────────────────────────────────────

def is_correlated_conflict(symbol: str, direction: str) -> bool:
    """
    direction: "BUY" ya "SELL" — jo naya signal aaya hai.
    Return True agar same group mein OPPOSITE direction
    ki trade pehle se open hai (conflict) — is case mein skip karo.
    """
    if "XAU" in symbol.upper():
        return False   # Gold ke liye correlation filter nahi

    positions = mt5.positions_get() or []
    open_map  = {p.symbol: ("BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL")
                 for p in positions}

    for group in config.CORRELATION_GROUPS:
        if symbol not in group:
            continue
        for other in group:
            if other == symbol or other not in open_map:
                continue
            other_dir = open_map[other]
            if other_dir != direction:
                log_event("INFO",
                    f"[{symbol}] {direction} conflicts with "
                    f"[{other}] {other_dir} (correlated group) — Skip."
                )
                return True
            else:
                log_event("INFO",
                    f"[{symbol}] {direction} matches [{other}] {other_dir} "
                    f"(same direction, correlated) — Allowed."
                )
    return False


def calculate_lot(symbol: str, sl_price: float, entry_price: float) -> float:
    try:
        acc = mt5.account_info()
        if acc is None:
            return config.LOT_SIZE_GOLD if "XAU" in symbol else config.LOT_SIZE_ICT

        equity      = acc.equity
        risk_pct    = config.RISK_PERCENT if "XAU" in symbol.upper() \
                      else config.RISK_PERCENT_FOREX
        risk_amount = equity * risk_pct

        info = mt5.symbol_info(symbol)
        if info is None:
            return config.LOT_SIZE_GOLD if "XAU" in symbol else config.LOT_SIZE_ICT

        min_lot, max_lot = info.volume_min, info.volume_max
        lot_step = info.volume_step or 0.01

        sl_distance = abs(entry_price - sl_price)
        if sl_distance <= 0:
            return min_lot

        tick_val, tick_size = info.trade_tick_value, info.trade_tick_size
        if tick_val > 0 and tick_size > 0:
            sl_dollar_per_lot = (sl_distance / tick_size) * tick_val
        else:
            point   = info.point
            sl_pips = sl_distance / point
            pv      = 6.5 if "JPY" in symbol.upper() else 10.0
            sl_dollar_per_lot = sl_pips * pv

        if sl_dollar_per_lot <= 0:
            return min_lot

        lot = risk_amount / sl_dollar_per_lot
        lot = round(round(lot / lot_step) * lot_step, 2)
        lot = max(min_lot, min(lot, max_lot))
        lot = max(lot, config.MIN_LOT_SIZE)

        log_event("INFO",
            f"[{symbol}] Lot:{lot} | Equity:${equity:.0f} "
            f"Risk:${risk_amount:.2f}({risk_pct*100:.1f}%) "
            f"SL_dist:{sl_distance:.5f}"
        )
        return lot
    except Exception as e:
        log_event("ERROR", f"[{symbol}] Lot calc error: {e}")
        return config.LOT_SIZE_GOLD if "XAU" in symbol else config.LOT_SIZE_ICT


def can_open_trade(symbol: str, direction: str = None) -> bool:
    """
    direction: agar diya ho to correlation direction-check bhi karega.
    """
    is_gold = "XAU" in symbol.upper()

    if is_daily_loss_limit_hit():
        return False

    positions = mt5.positions_get() or []
    sym_pos   = [p for p in positions if p.symbol == symbol]
    if sym_pos:
        log_event("INFO", f"[{symbol}] Already open — Skip.")
        return False

    if not is_spread_acceptable(symbol):
        return False

    try:
        import trade_memory as tm
        if tm.is_symbol_blocked(symbol):
            return False
    except Exception:
        pass

    if is_gold:
        return True

    forex_pos = [p for p in positions if "XAU" not in p.symbol.upper()]
    if len(forex_pos) >= config.MAX_OPEN_TRADES:
        log_event("INFO", f"[{symbol}] Forex max ({config.MAX_OPEN_TRADES}) — Wait.")
        return False

    sl_today = get_daily_sl_count(symbol)
    if sl_today >= config.MAX_DAILY_SL_PER_PAIR:
        log_event("INFO", f"[{symbol}] {sl_today} SL aaj — Max reached — Skip.")
        return False

    # Direction-aware correlation check — sirf agar direction pata ho
    if direction and is_correlated_conflict(symbol, direction):
        return False

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
