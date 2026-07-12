# ============================================================
#  logger.py — Events aur Errors Store Karta Hai
# ============================================================

import csv
import os
from datetime import datetime
import config

def _write_row(filepath, row):
    """CSV mein ek row likhta hai, file na ho to bana deta hai."""
    file_exists = os.path.isfile(filepath)
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(row["headers"])
        writer.writerow(row["data"])

def log_event(level: str, message: str):
    """
    Koi bhi event ya error logs.csv mein save karta hai.
    level: INFO | WARNING | ERROR
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] [{level}] {message}")

    _write_row(config.LOGS_FILE, {
        "headers": ["datetime", "level", "message"],
        "data":    [now, level, message]
    })

def log_trade(action, entry, sl, tp, lot, comment=""):
    """
    Trade ki details trades.csv mein save karta hai.
    action: OPEN | CLOSE | BREAK_EVEN
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    _write_row(config.TRADES_FILE, {
        "headers": ["datetime", "action", "entry", "sl", "tp", "lot", "comment"],
        "data":    [now, action, entry, sl, tp, lot, comment]
    })
    log_event("INFO", f"Trade logged — {action} | Entry:{entry} SL:{sl} TP:{tp}")