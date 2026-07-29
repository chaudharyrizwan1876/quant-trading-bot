# ============================================================
#  sessions/kill_zones.py — Session / Kill-Zone detection
#  Pure, config-driven, side-effect free (no logging) so it can
#  be reused by the live loop, the confidence engine, and the
#  backtester with an injectable clock (`now`) — backtests replay
#  historical timestamps, they can't rely on datetime.now().
# ============================================================

from datetime import datetime, timezone
import config


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def current_session(now: datetime = None) -> str:
    """
    Return active session label (kill-zone aware) or "OFF_SESSION".
    Values: PRE_LONDON | LONDON | PRE_NY | NEW_YORK | SILVER_BULLET | OFF_SESSION
    Order matches strategies/gold_hybrid._get_session() exactly.
    """
    now = now or _utc_now()
    h = now.hour

    if config.KILL_ZONE_PRE_LONDON_START <= h < config.KILL_ZONE_PRE_LONDON_END:
        return "PRE_LONDON"
    if config.KILL_ZONE_LONDON_START <= h < config.KILL_ZONE_LONDON_END:
        return "LONDON"
    if config.KILL_ZONE_PRE_NY_START <= h < config.KILL_ZONE_PRE_NY_END:
        return "PRE_NY"
    if config.KILL_ZONE_NY_START <= h < config.KILL_ZONE_NY_END:
        return "NEW_YORK"
    if is_silver_bullet_window(now):
        return "SILVER_BULLET"
    return "OFF_SESSION"


def is_silver_bullet_window(now: datetime = None) -> bool:
    now = now or _utc_now()
    h = now.hour
    return any(s <= h < e for s, e in config.SILVER_BULLET_WINDOWS)


def is_judas_window(now: datetime = None) -> bool:
    """Session open ke pehle 30 min — fake-out (Judas swing) window."""
    now = now or _utc_now()
    for start_h in (config.KILL_ZONE_LONDON_START, config.KILL_ZONE_NY_START):
        if now.hour == start_h and now.minute <= 30:
            return True
    return False


def is_prime_session(now: datetime = None) -> bool:
    """London / New York — highest-liquidity Gold windows."""
    return current_session(now) in ("LONDON", "NEW_YORK")
