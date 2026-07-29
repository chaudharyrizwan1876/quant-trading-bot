# ============================================================
#  news_reader.py — News Reader V2
#  File-based cache — restart ke baad bhi valid
#  429 error fix — 4 ghante cache, fallback URLs
# ============================================================

import urllib.request
import urllib.error
import socket
import json
import os
import time
from datetime import datetime, timezone, timedelta
from logger import log_event

# Global socket timeout
socket.setdefaulttimeout(10)

# ─────────────────────────────────────────────
#  Settings
# ─────────────────────────────────────────────
CACHE_FILE        = "data/news_cache.json"
CACHE_HOURS       = 6       # 6 ghante cache valid
MIN_FETCH_SECS    = 7200    # Minimum 2 ghante wait between fetches

# Multiple URLs — ek fail ho to dusra try karo
NEWS_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer":         "https://www.forexfactory.com/",
    "Connection":      "keep-alive",
}

# In-memory cache
_mem_cache      = []
_last_fetch_ts  = 0   # Unix timestamp


# ══════════════════════════════════════════════
#  FETCH WITH FILE CACHE
# ══════════════════════════════════════════════

def fetch_news() -> list:
    """
    News fetch karta hai — file cache use karta hai.
    Cache valid ho to server se fetch nahi karta.
    """
    global _mem_cache, _last_fetch_ts

    now_ts = time.time()
    now    = datetime.now(timezone.utc)

    # 1. Memory cache check
    if _mem_cache and (now_ts - _last_fetch_ts) < CACHE_HOURS * 3600:
        return _mem_cache

    # 2. File cache check
    cached = _load_file_cache()
    if cached is not None:
        _mem_cache     = cached
        _last_fetch_ts = now_ts
        return _mem_cache

    # 3. Rate limit check — kam se kam 1 ghanta wait
    if (now_ts - _last_fetch_ts) < MIN_FETCH_SECS and _mem_cache:
        log_event("INFO", "News: Rate limit wait — cache use kar raha hoon.")
        return _mem_cache

    # 4. Fetch from server
    raw = _fetch_from_server()
    if raw is None:
        log_event("WARNING", "News fetch fail — purana cache use ho raha hai.")
        return _mem_cache or []

    # 5. Parse
    news_list = _parse_news(raw, now)

    # 6. Save to file cache
    _save_file_cache(news_list)

    _mem_cache     = news_list
    _last_fetch_ts = now_ts

    log_event("INFO",
        f"News fetched: {len(news_list)} HIGH impact items")
    return news_list


def _fetch_from_server() -> list:
    """Multiple URLs try karo — ek kaam kare to return karo."""
    for url in NEWS_URLS:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
                log_event("INFO", f"News: Fetched from {url}")
                return data

        except urllib.error.HTTPError as e:
            if e.code == 429:
                log_event("WARNING",
                    f"News: 429 Rate limit on {url} — next URL try karta hoon."
                )
            else:
                log_event("WARNING", f"News: HTTP {e.code} on {url}")
            time.sleep(1)

        except Exception as e:
            log_event("WARNING", f"News: Error on {url}: {e}")
            time.sleep(1)

    return None


# ─────────────────────────────────────────────
#  FILE CACHE
# ─────────────────────────────────────────────

def _save_file_cache(news_list: list):
    """News data file mein save karo."""
    try:
        os.makedirs("data", exist_ok=True)
        payload = {
            "fetched_at": time.time(),
            "news":       news_list
        }
        # datetime objects ko string mein convert karo
        serializable = []
        for n in news_list:
            item = dict(n)
            if isinstance(item.get("time"), datetime):
                item["time"] = item["time"].isoformat()
            serializable.append(item)
        payload["news"] = serializable

        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    except Exception as e:
        log_event("WARNING", f"News cache save fail: {e}")


def _load_file_cache() -> list:
    """
    File cache load karo.
    Return: list agar valid cache hai, None agar expired ya missing
    """
    try:
        if not os.path.exists(CACHE_FILE):
            return None

        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)

        fetched_at = payload.get("fetched_at", 0)
        age_hours  = (time.time() - fetched_at) / 3600

        if age_hours > CACHE_HOURS:
            log_event("INFO",
                f"News: File cache expired ({age_hours:.1f}h old).")
            return None

        # datetime strings wapas convert karo
        news_list = []
        for item in payload.get("news", []):
            if isinstance(item.get("time"), str):
                try:
                    item["time"] = datetime.fromisoformat(item["time"])
                except Exception:
                    pass
            news_list.append(item)

        log_event("INFO",
            f"News: File cache loaded ({age_hours:.1f}h old, "
            f"{len(news_list)} items)."
        )
        return news_list

    except Exception as e:
        log_event("WARNING", f"News cache load fail: {e}")
        return None


# ─────────────────────────────────────────────
#  PARSE NEWS
# ─────────────────────────────────────────────

def _parse_news(raw: list, now: datetime) -> list:
    """Raw JSON se HIGH impact news parse karo."""
    news_list = []
    today     = now.date()

    for item in raw:
        try:
            news_time = datetime.strptime(
                item.get("date", ""), "%Y-%m-%dT%H:%M:%S%z"
            ).replace(tzinfo=timezone.utc)

            # Sirf aaj aur kal
            if news_time.date() not in [today, today + timedelta(days=1)]:
                continue

            impact   = item.get("impact", "").upper()
            currency = item.get("country", "").upper()

            if impact != "HIGH":
                continue

            title    = item.get("title",    "")
            actual   = item.get("actual",   "") or ""
            forecast = item.get("forecast", "") or ""
            previous = item.get("previous", "") or ""
            direction = _get_direction(actual, forecast, previous, title)

            news_list.append({
                "time":      news_time,
                "currency":  currency,
                "impact":    impact,
                "title":     title,
                "actual":    actual,
                "forecast":  forecast,
                "previous":  previous,
                "direction": direction,
            })

        except Exception:
            continue

    return news_list


# ─────────────────────────────────────────────
#  DIRECTION
# ─────────────────────────────────────────────

def _parse_num(s: str):
    if not s: return None
    try:
        s = s.strip().replace("%","").replace("K","000").replace("M","000000").replace(",","")
        return float(s)
    except Exception:
        return None

def _get_direction(actual, forecast, previous, title) -> str:
    a = _parse_num(actual)
    f = _parse_num(forecast)
    p = _parse_num(previous)
    if a is None: return "UNKNOWN"

    neg = any(kw in title.lower() for kw in
              ["unemployment","claims","deficit","inflation","cpi","ppi","jobless"])

    ref = f if f is not None else p
    if ref is None: return "UNKNOWN"

    if a > ref: return "BEARISH" if neg else "BULLISH"
    if a < ref: return "BULLISH" if neg else "BEARISH"
    return "NEUTRAL"


# ─────────────────────────────────────────────
#  NEWS SIGNAL
# ─────────────────────────────────────────────

def get_news_signal(symbol: str) -> dict:
    """Symbol ke liye news se trading direction."""
    no_signal = {"signal":"NO_TRADE","reason":"","news_time":None}

    news_list = fetch_news()
    if not news_list:
        return no_signal

    now = datetime.now(timezone.utc)

    # Recent USD news — 30 min pehle se 2 ghante baad tak
    recent = []
    for n in news_list:
        if not isinstance(n.get("time"), datetime):
            continue
        diff_h = (now - n["time"]).total_seconds() / 3600
        if n["currency"] == "USD" and n["direction"] != "UNKNOWN" and -0.5 <= diff_h <= 2.0:
            recent.append(n)

    if not recent:
        return {**no_signal, "reason": "Koi recent USD news nahi"}

    latest    = sorted(recent, key=lambda x: x["time"], reverse=True)[0]
    usd_dir   = latest["direction"]
    title     = latest["title"]
    news_time = latest["time"]

    log_event("INFO", f"News [{symbol}]: USD {usd_dir} — {title}")

    sym = symbol.upper()

    if "XAU" in sym:
        sig = "SELL" if usd_dir == "BULLISH" else "BUY"
    elif "JPY" in sym or "CAD" in sym:
        sig = "BUY"  if usd_dir == "BULLISH" else "SELL"
    else:   # EUR, GBP, AUD
        sig = "SELL" if usd_dir == "BULLISH" else "BUY"

    return {"signal":sig,"reason":f"USD {usd_dir}: {title}","news_time":news_time}


# ─────────────────────────────────────────────
#  UPCOMING NEWS CHECK
# ─────────────────────────────────────────────

def is_high_impact_soon(minutes_before: int = 15) -> bool:
    """Agle N min mein HIGH impact news aane wali hai?"""
    news_list = fetch_news()
    if not news_list: return False

    now = datetime.now(timezone.utc)
    for n in news_list:
        if not isinstance(n.get("time"), datetime): continue
        mins = (n["time"] - now).total_seconds() / 60
        if 0 <= mins <= minutes_before:
            log_event("INFO",
                f"Upcoming news in {mins:.0f} min: {n['title']} [{n['currency']}]"
            )
            return True
    return False


# ─────────────────────────────────────────────
#  PRINT TODAY'S NEWS
# ─────────────────────────────────────────────

def print_todays_news():
    news_list = fetch_news()
    if not news_list:
        log_event("INFO", "Koi HIGH impact news nahi mili.")
        return
    log_event("INFO", f"=== HIGH Impact News ({len(news_list)}) ===")
    for n in news_list:
        if isinstance(n.get("time"), datetime):
            t = n["time"].strftime("%d %b %H:%M UTC")
        else:
            t = str(n.get("time",""))
        log_event("INFO",
            f"  {t} [{n['currency']}] {n['title']} "
            f"A:{n['actual']} F:{n['forecast']} → {n['direction']}"
        )
