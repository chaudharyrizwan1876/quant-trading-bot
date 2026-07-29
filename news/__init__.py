# ============================================================
#  news — high-impact economic calendar filter + bias
# ============================================================

from .news_reader import (
    fetch_news,
    get_news_signal,
    is_high_impact_soon,
    print_todays_news,
)

__all__ = [
    "fetch_news",
    "get_news_signal",
    "is_high_impact_soon",
    "print_todays_news",
]
