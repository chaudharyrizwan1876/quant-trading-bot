# ============================================================
#  risk — position sizing, SL capping, exposure/loss guards
# ============================================================

from .risk_manager import (
    record_sl_hit,
    get_daily_sl_count,
    is_daily_loss_limit_hit,
    is_spread_acceptable,
    calculate_lot_and_sl,
    calculate_lot,
    can_open_trade,
    get_open_trade_count,
    score_signal,
)

__all__ = [
    "record_sl_hit",
    "get_daily_sl_count",
    "is_daily_loss_limit_hit",
    "is_spread_acceptable",
    "calculate_lot_and_sl",
    "calculate_lot",
    "can_open_trade",
    "get_open_trade_count",
    "score_signal",
]
