# ============================================================
#  trade_memory.py — V2 (Stricter, Symbol+Pattern Granular)
#
#  NAYA:
#  - Har (symbol + pattern) combo alag track hota hai
#    (e.g. "EURUSDm_OB_Q" alag hai "GBPUSDm_OB_Q" se)
#  - Sirf 2 losses (24h mein) → 24h ke liye us combo pe
#    trading BAND (pehle 3 losses/48h tha — bahut loose tha)
#  - Symbol-level win rate bhi track hoti hai — agar
#    kisi pair ka win rate 35% se kam ho (min 5 trades ke
#    baad), poora symbol 24h ke liye block ho jata hai
#    (chahe pattern kuch bhi ho)
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from logger import log_event

MEMORY_FILE = "data/trade_memory.json"

LOSS_THRESHOLD   = 2      # Itni losses (window ke andar) = block
LOSS_WINDOW_HRS  = 24     # Kitne ghante ke andar losses count hon
BLOCK_HOURS      = 24     # Block kitne ghante ka
MIN_TRADES_WR    = 5      # Win-rate check ke liye minimum trades
MIN_WIN_RATE     = 0.35   # Isse kam win rate = symbol block

_memory = None


def _load():
    global _memory
    if _memory is not None:
        return _memory
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                _memory = json.load(f)
        else:
            _memory = {"combos": {}, "symbols": {}}
    except Exception:
        _memory = {"combos": {}, "symbols": {}}
    if "combos" not in _memory: _memory["combos"] = {}
    if "symbols" not in _memory: _memory["symbols"] = {}
    return _memory


def _save():
    try:
        os.makedirs("data", exist_ok=True)
        with open(MEMORY_FILE, "w") as f:
            json.dump(_memory, f, indent=2)
    except Exception as e:
        log_event("WARNING", f"Memory save fail: {e}")


def _get_pattern(comment: str) -> str:
    comment = comment.upper()
    if "OB_FVG" in comment: return "OB_FVG"
    if "OB_Q"   in comment: return "OB_Q"
    if "OB"     in comment: return "OB"
    if "FVG"    in comment: return "FVG"
    if "LIQ"    in comment: return "LIQ"
    if "BREAKER"in comment: return "BREAKER"
    if "AMD"    in comment: return "AMD"
    if "SB_"    in comment or "SILVER" in comment: return "SB"
    if "NEWS"   in comment: return "NEWS"
    return "OTHER"


def _combo_key(symbol: str, pattern: str) -> str:
    return f"{symbol}_{pattern}"


# ─────────────────────────────────────────────
#  RECORD RESULT
# ─────────────────────────────────────────────

def record_result(symbol: str, comment: str, profit: float, was_sl: bool):
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    now_str = datetime.now(timezone.utc).isoformat()
    is_loss = was_sl or profit < 0

    # ── Combo (symbol+pattern) tracking ──
    if key not in mem["combos"]:
        mem["combos"][key] = {"wins":0,"losses":0,"recent_losses":[],"blocked_until":None}
    c = mem["combos"][key]

    if is_loss:
        c["losses"] += 1
        c["recent_losses"].append(now_str)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOSS_WINDOW_HRS)).isoformat()
        c["recent_losses"] = [t for t in c["recent_losses"] if t > cutoff]

        if len(c["recent_losses"]) >= LOSS_THRESHOLD:
            blocked = (datetime.now(timezone.utc) + timedelta(hours=BLOCK_HOURS)).isoformat()
            c["blocked_until"] = blocked
            log_event("WARNING",
                f"[{symbol}] Pattern [{pattern}] {len(c['recent_losses'])} "
                f"losses in {LOSS_WINDOW_HRS}h — BLOCKED {BLOCK_HOURS}h!"
            )
    else:
        c["wins"] += 1
        c["recent_losses"] = []
        c["blocked_until"] = None

    # ── Symbol-level overall tracking (win rate) ──
    if symbol not in mem["symbols"]:
        mem["symbols"][symbol] = {"wins":0,"losses":0,"recent_losses":[],"blocked_until":None}
    s = mem["symbols"][symbol]

    if is_loss:
        s["losses"] += 1
        s["recent_losses"].append(now_str)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOSS_WINDOW_HRS)).isoformat()
        s["recent_losses"] = [t for t in s["recent_losses"] if t > cutoff]
    else:
        s["wins"] += 1
        s["recent_losses"] = []

    total = s["wins"] + s["losses"]
    if total >= MIN_TRADES_WR:
        win_rate = s["wins"] / total
        if win_rate < MIN_WIN_RATE:
            blocked = (datetime.now(timezone.utc) + timedelta(hours=BLOCK_HOURS)).isoformat()
            s["blocked_until"] = blocked
            log_event("WARNING",
                f"[{symbol}] Overall win rate {win_rate*100:.0f}% "
                f"(< {MIN_WIN_RATE*100:.0f}%) after {total} trades — "
                f"SYMBOL BLOCKED {BLOCK_HOURS}h!"
            )
        elif s.get("blocked_until"):
            s["blocked_until"] = None   # win rate improve ho gaya

    log_event("INFO",
        f"Memory: [{symbol}][{pattern}] W:{c['wins']} L:{c['losses']} | "
        f"Symbol overall W:{s['wins']} L:{s['losses']}"
    )
    _save()


# ─────────────────────────────────────────────
#  BLOCK CHECKS
# ─────────────────────────────────────────────

def is_pattern_blocked(symbol: str, comment: str) -> bool:
    """
    Ab symbol+pattern dono ke hisaab se check karta hai —
    sirf pattern nahi (jaise pehle tha, jo bahut loose tha).
    """
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    now_str = datetime.now(timezone.utc).isoformat()

    c = mem.get("combos", {}).get(key, {})
    blocked_until = c.get("blocked_until")

    if blocked_until and now_str < blocked_until:
        log_event("INFO",
            f"[{symbol}] Pattern [{pattern}] blocked until "
            f"{blocked_until} — Skip."
        )
        return True
    elif blocked_until and now_str >= blocked_until:
        mem["combos"][key]["blocked_until"] = None
        mem["combos"][key]["recent_losses"] = []
        _save()

    return False


def is_symbol_blocked(symbol: str) -> bool:
    mem     = _load()
    now_str = datetime.now(timezone.utc).isoformat()

    s = mem.get("symbols", {}).get(symbol, {})
    blocked_until = s.get("blocked_until")

    if blocked_until and now_str < blocked_until:
        log_event("INFO",
            f"[{symbol}] Symbol blocked (poor win rate) until "
            f"{blocked_until} — Skip."
        )
        return True
    elif blocked_until and now_str >= blocked_until:
        mem["symbols"][symbol]["blocked_until"] = None
        mem["symbols"][symbol]["recent_losses"] = []
        _save()

    return False


# ─────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
#  ADAPTIVE LEARNING — Continuous Score Adjustment
#
#  Yeh asal "seekhne" wala mechanism hai — hard block ke
#  ilawa, har (symbol+pattern) combo ka apna live win-rate
#  based bonus/penalty hota hai. Jo scenario zyada TP de
#  raha hai uska score badhta jata hai (priority milti hai),
#  jo scenario zyada SL de raha hai uska score girta jata hai
#  — bot khud-ba-khud behtar setups ki taraf jhukta hai,
#  bina kisi manual intervention ke.
# ─────────────────────────────────────────────

MIN_TRADES_ADAPTIVE = 3   # Itni trades ke baad hi adjustment lagu hoga

def get_adaptive_score(symbol: str, comment: str) -> float:
    """
    (symbol+pattern) combo ka live performance dekh kar
    score bonus/penalty return karta hai:

    Win rate >= 65%  → +20  (bahut acha scenario — priority)
    Win rate >= 50%  → +10  (acha scenario)
    Win rate >= 35%  → 0    (neutral)
    Win rate <  35%  → -25  (bura scenario — heavily penalize)

    Kam trades (< MIN_TRADES_ADAPTIVE) → 0 (abhi data kam hai)
    """
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    c       = mem.get("combos", {}).get(key, {})

    total = c.get("wins", 0) + c.get("losses", 0)
    if total < MIN_TRADES_ADAPTIVE:
        return 0.0

    win_rate = c["wins"] / total

    if win_rate >= 0.65:
        adj = 20.0
    elif win_rate >= 0.50:
        adj = 10.0
    elif win_rate >= 0.35:
        adj = 0.0
    else:
        adj = -25.0

    log_event("INFO",
        f"[{symbol}][{pattern}] Adaptive: WR={win_rate*100:.0f}% "
        f"({c['wins']}W/{c['losses']}L) → Score adj: {adj:+.0f}"
    )
    return adj


def print_stats():
    mem = _load()
    log_event("INFO", "=== Trade Memory Stats ===")
    for key, data in mem.get("combos", {}).items():
        total = data["wins"] + data["losses"]
        wr = (data["wins"]/total*100) if total>0 else 0
        status = f"BLOCKED till {data.get('blocked_until')}" if data.get("blocked_until") else "Active"
        log_event("INFO", f"  [{key}]: W:{data['wins']} L:{data['losses']} WR:{wr:.0f}% | {status}")

    for sym, data in mem.get("symbols", {}).items():
        total = data["wins"] + data["losses"]
        wr = (data["wins"]/total*100) if total>0 else 0
        status = "BLOCKED" if data.get("blocked_until") else "Active"
        log_event("INFO", f"  [{sym}] Overall: W:{data['wins']} L:{data['losses']} WR:{wr:.0f}% | {status}")
