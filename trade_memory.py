# ============================================================
#  trade_memory.py — Simple Trade Learning System
#  Har trade ka result save karta hai
#  Same pattern 3 baar SL de to 24 hours block
#  Win rate per pattern track karta hai
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from logger import log_event

MEMORY_FILE = "data/trade_memory.json"

# ─────────────────────────────────────────────
#  MEMORY STRUCTURE
# {
#   "patterns": {
#     "OB_M15": {
#       "wins": 5, "losses": 2,
#       "recent_losses": ["2026-07-06T10:00:00", ...],
#       "blocked_until": null or "2026-07-06T15:00:00"
#     }
#   },
#   "symbols": {
#     "EURUSDm": {
#       "wins": 3, "losses": 1,
#       "recent_losses": [...],
#       "blocked_until": null
#     }
#   }
# }
# ─────────────────────────────────────────────

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
            _memory = {"patterns": {}, "symbols": {}}
    except Exception:
        _memory = {"patterns": {}, "symbols": {}}
    return _memory


def _save():
    try:
        os.makedirs("data", exist_ok=True)
        with open(MEMORY_FILE, "w") as f:
            json.dump(_memory, f, indent=2)
    except Exception as e:
        log_event("WARNING", f"Memory save fail: {e}")


def _get_pattern(comment: str) -> str:
    """Comment se pattern type nikalo."""
    comment = comment.upper()
    if "OB_FVG" in comment: return "OB_FVG"
    if "OB_Q"   in comment: return "OB_Q"
    if "OB"     in comment: return "OB"
    if "FVG"    in comment: return "FVG"
    if "LIQ"    in comment: return "LIQ"
    if "BREAKER"in comment: return "BREAKER"
    if "NEWS"   in comment: return "NEWS"
    return "OTHER"


# ─────────────────────────────────────────────
#  RECORD TRADE RESULT
# ─────────────────────────────────────────────

def record_result(symbol: str, comment: str,
                  profit: float, was_sl: bool):
    """
    Trade close hone par call karo.
    profit: actual P&L
    was_sl: True agar SL hit hua
    """
    mem     = _load()
    pattern = _get_pattern(comment)
    now_str = datetime.now(timezone.utc).isoformat()

    # Pattern stats update
    if pattern not in mem["patterns"]:
        mem["patterns"][pattern] = {
            "wins": 0, "losses": 0,
            "recent_losses": [], "blocked_until": None
        }

    p = mem["patterns"][pattern]

    if was_sl or profit < 0:
        p["losses"] += 1
        p["recent_losses"].append(now_str)
        # Sirf last 48 ghante ki losses rakho
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(hours=48)).isoformat()
        p["recent_losses"] = [t for t in p["recent_losses"] if t > cutoff]

        # 3 consecutive losses → 24 hour block
        if len(p["recent_losses"]) >= 3:
            blocked = (datetime.now(timezone.utc) +
                       timedelta(hours=24)).isoformat()
            p["blocked_until"] = blocked
            log_event("WARNING",
                f"Pattern [{pattern}] 3 SL in 48h — "
                f"BLOCKED for 24 hours!"
            )
    else:
        p["wins"] += 1
        # Win hone par recent losses reset
        p["recent_losses"] = []
        p["blocked_until"] = None

    # Symbol stats update
    if symbol not in mem["symbols"]:
        mem["symbols"][symbol] = {
            "wins": 0, "losses": 0,
            "recent_losses": [], "blocked_until": None
        }

    s = mem["symbols"][symbol]

    if was_sl or profit < 0:
        s["losses"] += 1
        s["recent_losses"].append(now_str)
        cutoff = (datetime.now(timezone.utc) -
                  timedelta(hours=48)).isoformat()
        s["recent_losses"] = [t for t in s["recent_losses"] if t > cutoff]

        # Symbol pe 3 losses → 12 hour block
        if len(s["recent_losses"]) >= 3:
            blocked = (datetime.now(timezone.utc) +
                       timedelta(hours=12)).isoformat()
            s["blocked_until"] = blocked
            log_event("WARNING",
                f"Symbol [{symbol}] 3 SL in 48h — "
                f"BLOCKED for 12 hours!"
            )
    else:
        s["wins"] += 1
        s["recent_losses"] = []
        s["blocked_until"] = None

    total = p["wins"] + p["losses"]
    win_rate = (p["wins"] / total * 100) if total > 0 else 0
    log_event("INFO",
        f"Memory: [{pattern}] W:{p['wins']} L:{p['losses']} "
        f"WR:{win_rate:.0f}% | [{symbol}] "
        f"W:{s['wins']} L:{s['losses']}"
    )

    _save()


# ─────────────────────────────────────────────
#  IS BLOCKED CHECK
# ─────────────────────────────────────────────

def is_pattern_blocked(comment: str) -> bool:
    """Kya yeh pattern abhi blocked hai?"""
    mem     = _load()
    pattern = _get_pattern(comment)
    now_str = datetime.now(timezone.utc).isoformat()

    p = mem.get("patterns", {}).get(pattern, {})
    blocked_until = p.get("blocked_until")

    if blocked_until and now_str < blocked_until:
        log_event("INFO",
            f"Pattern [{pattern}] blocked until {blocked_until} — Skip.")
        return True
    elif blocked_until and now_str >= blocked_until:
        # Block expire ho gaya
        mem["patterns"][pattern]["blocked_until"] = None
        mem["patterns"][pattern]["recent_losses"] = []
        _save()

    return False


def is_symbol_blocked(symbol: str) -> bool:
    """Kya yeh symbol abhi blocked hai?"""
    mem     = _load()
    now_str = datetime.now(timezone.utc).isoformat()

    s = mem.get("symbols", {}).get(symbol, {})
    blocked_until = s.get("blocked_until")

    if blocked_until and now_str < blocked_until:
        log_event("INFO",
            f"Symbol [{symbol}] blocked until {blocked_until} — Skip.")
        return True
    elif blocked_until and now_str >= blocked_until:
        mem["symbols"][symbol]["blocked_until"] = None
        mem["symbols"][symbol]["recent_losses"] = []
        _save()

    return False


# ─────────────────────────────────────────────
#  STATS PRINT
# ─────────────────────────────────────────────

def print_stats():
    """Saari patterns ki win rate print karo."""
    mem = _load()

    log_event("INFO", "=== Trade Memory Stats ===")

    for pattern, data in mem.get("patterns", {}).items():
        total    = data["wins"] + data["losses"]
        win_rate = (data["wins"] / total * 100) if total > 0 else 0
        blocked  = data.get("blocked_until", "")
        status   = f"BLOCKED till {blocked}" if blocked else "Active"
        log_event("INFO",
            f"  Pattern [{pattern}]: "
            f"W:{data['wins']} L:{data['losses']} "
            f"WR:{win_rate:.0f}% | {status}"
        )

    for symbol, data in mem.get("symbols", {}).items():
        total    = data["wins"] + data["losses"]
        win_rate = (data["wins"] / total * 100) if total > 0 else 0
        blocked  = data.get("blocked_until", "")
        status   = f"BLOCKED" if blocked else "Active"
        log_event("INFO",
            f"  Symbol [{symbol}]: "
            f"W:{data['wins']} L:{data['losses']} "
            f"WR:{win_rate:.0f}% | {status}"
        )
