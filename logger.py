# ============================================================
#  logger.py — Events aur Errors Store Karta Hai
#  V2: buffered + size-rotated CSV writer.
#  Purana version har log_event() call pe file open/append/close
#  karta tha — 5s loop mein dozens of calls, isse data/logs.csv
#  337MB+ tak ban gayi thi aur kabhi rotate nahi hoti thi. Ab
#  file handle open rehta hai (periodic flush) aur size threshold
#  cross hote hi automatically archive+rotate hota hai.
# ============================================================

import atexit
import csv
import os
from datetime import datetime
import config

_MAX_LOG_BYTES     = 20 * 1024 * 1024   # 20MB — isse zyada ho to rotate
_FLUSH_EVERY_ROWS  = 20
_ROTATE_CHECK_EVERY = 500               # har N rows pe size dobara check karo

_handles = {}   # filepath -> {"file", "writer", "headers", "unflushed", "since_check"}


def _archive_if_oversized(filepath: str):
    try:
        if os.path.exists(filepath) and os.path.getsize(filepath) > _MAX_LOG_BYTES:
            base, ext = os.path.splitext(filepath)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            os.replace(filepath, f"{base}.{stamp}{ext}")
    except Exception:
        pass


def _open_handle(filepath: str, headers: list):
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    _archive_if_oversized(filepath)
    file_exists = os.path.isfile(filepath) and os.path.getsize(filepath) > 0
    f = open(filepath, "a", newline="", encoding="utf-8")
    writer = csv.writer(f)
    if not file_exists:
        writer.writerow(headers)
        f.flush()
    return {"file": f, "writer": writer, "headers": headers,
            "unflushed": 0, "since_check": 0}


def _get_handle(filepath: str, headers: list):
    h = _handles.get(filepath)
    if h is None:
        h = _open_handle(filepath, headers)
        _handles[filepath] = h
    return h


def _write_row(filepath: str, headers: list, data: list):
    h = _get_handle(filepath, headers)
    h["writer"].writerow(data)
    h["unflushed"] += 1
    h["since_check"] += 1

    if h["unflushed"] >= _FLUSH_EVERY_ROWS:
        h["file"].flush()
        h["unflushed"] = 0

    if h["since_check"] >= _ROTATE_CHECK_EVERY:
        h["since_check"] = 0
        h["file"].flush()
        if os.path.getsize(filepath) > _MAX_LOG_BYTES:
            h["file"].close()
            del _handles[filepath]
            _get_handle(filepath, headers)   # reopen fresh (archives old one)


def log_event(level: str, message: str):
    """
    Koi bhi event ya error logs.csv mein save karta hai.
    level: INFO | WARNING | ERROR

    config.LOG_TO_CONSOLE = False (e.g. backtest) → console quiet,
    file logging phir bhi hoti hai.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if getattr(config, "LOG_TO_CONSOLE", True):
        print(f"[{now}] [{level}] {message}")

    _write_row(config.LOGS_FILE, ["datetime", "level", "message"], [now, level, message])


def log_trade(action, entry, sl, tp, lot, comment=""):
    """
    Trade ki details trades.csv mein save karta hai.
    action: OPEN | CLOSE | BREAK_EVEN
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _write_row(config.TRADES_FILE,
               ["datetime", "action", "entry", "sl", "tp", "lot", "comment"],
               [now, action, entry, sl, tp, lot, comment])
    log_event("INFO", f"Trade logged — {action} | Entry:{entry} SL:{sl} TP:{tp}")


@atexit.register
def _flush_and_close_all():
    for h in _handles.values():
        try:
            h["file"].flush()
            h["file"].close()
        except Exception:
            pass
