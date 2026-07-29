# ============================================================
#  sessions — kill-zone / session detection (pure functions)
# ============================================================

from .kill_zones import (
    current_session,
    is_silver_bullet_window,
    is_judas_window,
    is_prime_session,
)

__all__ = [
    "current_session",
    "is_silver_bullet_window",
    "is_judas_window",
    "is_prime_session",
]
