# ============================================================
#  trade_memory.py — V8.4
#  Pattern+Symbol granular tracking, adaptive scoring,
#  hour-of-day learning, hard-block after repeated losses
# ============================================================

import json
import os
from datetime import datetime, timezone, timedelta
from logger import log_event

MEMORY_FILE = "data/trade_memory.json"

LOSS_THRESHOLD  = 2      # Itni losses (window ke andar) = block
LOSS_WINDOW_HRS = 24
BLOCK_HOURS     = 24
MIN_TRADES_WR   = 5
MIN_WIN_RATE    = 0.35
MIN_TRADES_ADAPTIVE = 3

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
            _memory = {"combos": {}, "symbols": {}, "hours": {}}
    except Exception:
        _memory = {"combos": {}, "symbols": {}, "hours": {}}
    for k in ("combos", "symbols", "hours"):
        if k not in _memory: _memory[k] = {}
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
    if "INST_SWEEP" in comment: return "INST_SWEEP"
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


def record_result(symbol: str, comment: str, profit: float, was_sl: bool):
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    now_str = datetime.now(timezone.utc).isoformat()
    is_loss = was_sl or profit < 0

    hour        = datetime.now(timezone.utc).hour
    hour_bucket = hour // 3
    hour_key    = f"{symbol}_hour{hour_bucket}"
    if hour_key not in mem["hours"]:
        mem["hours"][hour_key] = {"wins":0,"losses":0}
    if is_loss:
        mem["hours"][hour_key]["losses"] += 1
    else:
        mem["hours"][hour_key]["wins"] += 1

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
                f"after {total} trades — SYMBOL BLOCKED {BLOCK_HOURS}h!"
            )
        elif s.get("blocked_until"):
            s["blocked_until"] = None

    log_event("INFO",
        f"Memory: [{symbol}][{pattern}] W:{c['wins']} L:{c['losses']} | "
        f"Symbol overall W:{s['wins']} L:{s['losses']}"
    )
    _save()


def is_pattern_blocked(symbol: str, comment: str) -> bool:
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    now_str = datetime.now(timezone.utc).isoformat()

    c = mem.get("combos", {}).get(key, {})
    blocked_until = c.get("blocked_until")

    if blocked_until and now_str < blocked_until:
        log_event("INFO", f"[{symbol}] Pattern [{pattern}] blocked until {blocked_until} — Skip.")
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
        log_event("INFO", f"[{symbol}] Symbol blocked (poor win rate) until {blocked_until} — Skip.")
        return True
    elif blocked_until and now_str >= blocked_until:
        mem["symbols"][symbol]["blocked_until"] = None
        mem["symbols"][symbol]["recent_losses"] = []
        _save()
    return False


def get_adaptive_score(symbol: str, comment: str) -> float:
    mem     = _load()
    pattern = _get_pattern(comment)
    key     = _combo_key(symbol, pattern)
    c       = mem.get("combos", {}).get(key, {})
    total   = c.get("wins", 0) + c.get("losses", 0)
    if total < MIN_TRADES_ADAPTIVE:
        return 0.0
    win_rate = c["wins"] / total
    if win_rate >= 0.65: adj = 20.0
    elif win_rate >= 0.50: adj = 10.0
    elif win_rate >= 0.35: adj = 0.0
    else: adj = -25.0
    log_event("INFO",
        f"[{symbol}][{pattern}] Adaptive: WR={win_rate*100:.0f}% "
        f"({c['wins']}W/{c['losses']}L) → Score adj: {adj:+.0f}"
    )
    return adj


def get_hour_adaptive_score(symbol: str) -> float:
    mem  = _load()
    hour = datetime.now(timezone.utc).hour
    hour_bucket = hour // 3
    hour_key = f"{symbol}_hour{hour_bucket}"
    h = mem.get("hours", {}).get(hour_key, {})
    total = h.get("wins", 0) + h.get("losses", 0)
    if total < 3:
        return 0.0
    win_rate = h["wins"] / total
    if win_rate >= 0.65: adj = 10.0
    elif win_rate >= 0.50: adj = 5.0
    elif win_rate >= 0.35: adj = 0.0
    else: adj = -10.0
    log_event("INFO",
        f"[{symbol}] Hour-bucket {hour_bucket} WR={win_rate*100:.0f}% "
        f"({h['wins']}W/{h['losses']}L) → Score adj: {adj:+.0f}"
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
