# ============================================================
#  backtesting/clock.py — Frozen-clock adapter for replay
# ============================================================
#
#  Live strategies datetime.now(timezone.utc) par heavily depend
#  karti hain (sessions, kill zones, weekend cutoff, Judas window,
#  weekly quota). Backtest mein hum historical bar-time ko "ab" ki
#  tarah dikhana chahte hain — bina live strategy code ko modify
#  kiye (production money code chhedna risky hai).
#
#  Yeh context manager har diye gaye module ke `datetime` symbol
#  ko ek frozen subclass se replace kar deta hai jiska .now()
#  simulated time deta hai. Non-invasive, standard technique.
# ============================================================

from contextlib import contextmanager
from datetime import datetime as _RealDateTime


def _make_frozen(frozen_dt):
    class _FrozenDateTime(_RealDateTime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None and frozen_dt.tzinfo is None:
                return frozen_dt.replace(tzinfo=tz)
            if tz is not None:
                return frozen_dt.astimezone(tz)
            return frozen_dt

        @classmethod
        def utcnow(cls):
            return frozen_dt.replace(tzinfo=None)

    return _FrozenDateTime


@contextmanager
def frozen_time(frozen_dt, modules):
    """
    frozen_dt: timezone-aware datetime representing simulated "now".
    modules:   list of module objects whose top-level `datetime`
               symbol should be frozen for the duration.

    Sirf un modules mein patch hota hai jinke andar
    `from datetime import datetime` kiya gaya ho.
    """
    frozen_cls = _make_frozen(frozen_dt)
    saved = {}
    for m in modules:
        if hasattr(m, "datetime"):
            saved[m] = m.datetime
            m.datetime = frozen_cls
    try:
        yield
    finally:
        for m, original in saved.items():
            m.datetime = original
