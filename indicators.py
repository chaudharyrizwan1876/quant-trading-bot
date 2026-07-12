# ============================================================
#  indicators.py — ICT + SMC Indicators
# ============================================================
#
#  Yeh file calculate karta hai:
#  1. BOS  — Break of Structure
#  2. CHOCH — Change of Character
#  3. Order Blocks (Bullish + Bearish)
#  4. Fair Value Gaps (FVG)
#  5. Liquidity Levels (swing highs/lows)
# ============================================================

import pandas as pd
import config
from logger import log_event

# ─────────────────────────────────────────────
#  1. MARKET STRUCTURE: BOS + CHOCH
# ─────────────────────────────────────────────

def get_market_structure(df) -> dict:
    """
    H1 candles pe market structure analyze karta hai.

    BOS  (Break of Structure):
         Trend continuation — price previous high/low tod deti hai
         Bullish BOS = price previous swing high tod kar upar jaaye
         Bearish BOS = price previous swing low tod kar neeche jaaye

    CHOCH (Change of Character):
         Trend reversal signal
         Bullish CHOCH = bearish trend mein price previous swing high tod le
         Bearish CHOCH = bullish trend mein price previous swing low tod le

    Return:
    {
        "trend":        "BULLISH" | "BEARISH" | "NONE",
        "structure":    "BOS" | "CHOCH" | "NONE",
        "swing_high":   float,
        "swing_low":    float,
        "last_bos":     "BULLISH" | "BEARISH" | None
    }
    """
    if df is None or len(df) < config.STRUCTURE_LOOKBACK + 5:
        return {"trend": "NONE", "structure": "NONE",
                "swing_high": 0, "swing_low": 0, "last_bos": None}

    lookback = config.STRUCTURE_LOOKBACK
    candles  = df.iloc[:-1].reset_index(drop=True)  # closed candles

    # Swing highs aur lows dhundho
    swing_highs = []
    swing_lows  = []

    for i in range(2, len(candles) - 2):
        c = candles.iloc[i]
        # Swing High: dono taraf se neeche
        if (c["high"] > candles.iloc[i-1]["high"] and
            c["high"] > candles.iloc[i-2]["high"] and
            c["high"] > candles.iloc[i+1]["high"] and
            c["high"] > candles.iloc[i+2]["high"]):
            swing_highs.append({"idx": i, "price": c["high"], "time": c["time"]})

        # Swing Low: dono taraf se upar
        if (c["low"] < candles.iloc[i-1]["low"] and
            c["low"] < candles.iloc[i-2]["low"] and
            c["low"] < candles.iloc[i+1]["low"] and
            c["low"] < candles.iloc[i+2]["low"]):
            swing_lows.append({"idx": i, "price": c["low"], "time": c["time"]})

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return {"trend": "NONE", "structure": "NONE",
                "swing_high": 0, "swing_low": 0, "last_bos": None}

    # Last 2 swing highs aur lows
    last_sh  = swing_highs[-1]["price"]
    prev_sh  = swing_highs[-2]["price"]
    last_sl  = swing_lows[-1]["price"]
    prev_sl  = swing_lows[-2]["price"]

    current_close = candles.iloc[-1]["close"]

    # Trend determine karo
    # Bullish: higher highs + higher lows
    # Bearish: lower highs + lower lows
    if last_sh > prev_sh and last_sl > prev_sl:
        trend = "BULLISH"
    elif last_sh < prev_sh and last_sl < prev_sl:
        trend = "BEARISH"
    else:
        trend = "NONE"

    # BOS check
    structure = "NONE"
    last_bos  = None

    if current_close > last_sh:
        structure = "BOS"
        last_bos  = "BULLISH"
    elif current_close < last_sl:
        structure = "BOS"
        last_bos  = "BEARISH"

    # CHOCH check — trend ke against structure break
    if trend == "BEARISH" and current_close > last_sh:
        structure = "CHOCH"
        last_bos  = "BULLISH"
    elif trend == "BULLISH" and current_close < last_sl:
        structure = "CHOCH"
        last_bos  = "BEARISH"

    log_event("INFO",
        f"Structure — Trend:{trend} | {structure} | "
        f"SH:{last_sh:.3f} SL:{last_sl:.3f}"
    )

    return {
        "trend":      trend,
        "structure":  structure,
        "swing_high": last_sh,
        "swing_low":  last_sl,
        "last_bos":   last_bos
    }

# ─────────────────────────────────────────────
#  2. ORDER BLOCKS
# ─────────────────────────────────────────────

def get_order_blocks(df, direction: str) -> list:
    """
    M15 candles pe Order Blocks identify karta hai.

    Bullish OB (BUY ke liye):
      - Strong bullish candle se pehle wali bearish candle
      - Us bearish candle ka body = OB zone

    Bearish OB (SELL ke liye):
      - Strong bearish candle se pehle wali bullish candle
      - Us bullish candle ka body = OB zone

    direction: "BULLISH" ya "BEARISH"

    Return: list of OBs sorted by recency
    [
        {
            "top":    float,
            "bottom": float,
            "mid":    float,
            "idx":    int,
            "time":   timestamp,
            "type":   "BULLISH" | "BEARISH"
        }
    ]
    """
    if df is None or len(df) < 5:
        return []

    closed  = df.iloc[:-1].reset_index(drop=True)
    lookback = min(config.OB_LOOKBACK, len(closed) - 1)
    obs      = []

    for i in range(1, lookback):
        curr = closed.iloc[i]
        prev = closed.iloc[i - 1]

        if direction == "BULLISH":
            # Strong bullish candle dhundho
            curr_body = curr["close"] - curr["open"]
            if curr_body < config.OB_MIN_SIZE:
                continue
            if curr["close"] < curr["open"]:  # bearish candle skip
                continue
            # Pehle wali candle bearish honi chahiye = OB
            if prev["close"] < prev["open"]:
                ob_top    = max(prev["open"], prev["close"])
                ob_bottom = min(prev["open"], prev["close"])
                obs.append({
                    "top":    ob_top,
                    "bottom": ob_bottom,
                    "mid":    (ob_top + ob_bottom) / 2,
                    "idx":    i - 1,
                    "time":   prev["time"],
                    "type":   "BULLISH"
                })

        elif direction == "BEARISH":
            # Strong bearish candle dhundho
            curr_body = curr["open"] - curr["close"]
            if curr_body < config.OB_MIN_SIZE:
                continue
            if curr["close"] > curr["open"]:  # bullish candle skip
                continue
            # Pehle wali candle bullish honi chahiye = OB
            if prev["close"] > prev["open"]:
                ob_top    = max(prev["open"], prev["close"])
                ob_bottom = min(prev["open"], prev["close"])
                obs.append({
                    "top":    ob_top,
                    "bottom": ob_bottom,
                    "mid":    (ob_top + ob_bottom) / 2,
                    "idx":    i - 1,
                    "time":   prev["time"],
                    "type":   "BEARISH"
                })

    # Recent OBs pehle
    obs.reverse()

    if obs:
        log_event("INFO", f"{direction} OBs mily: {len(obs)} — "
                          f"Latest OB: {obs[0]['bottom']:.3f}-{obs[0]['top']:.3f}")

    return obs

# ─────────────────────────────────────────────
#  3. FAIR VALUE GAP (FVG / IFVG)
# ─────────────────────────────────────────────

def get_fvg(df, direction: str) -> list:
    """
    M5 candles pe Fair Value Gaps identify karta hai.

    Bullish FVG:
      Candle[i-1] high < Candle[i+1] low
      = Gap hai beech mein — price fill karne wapas aayegi

    Bearish FVG:
      Candle[i-1] low > Candle[i+1] high
      = Gap hai — price fill karne wapas aayegi

    direction: "BULLISH" ya "BEARISH"

    Return: list of FVGs
    [
        {
            "top":    float,
            "bottom": float,
            "mid":    float,
            "idx":    int,
            "time":   timestamp
        }
    ]
    """
    if df is None or len(df) < 5:
        return []

    closed   = df.iloc[:-1].reset_index(drop=True)
    lookback = min(config.FVG_LOOKBACK, len(closed) - 2)
    fvgs     = []

    for i in range(1, lookback):
        if i + 1 >= len(closed):
            break

        prev = closed.iloc[i - 1]
        curr = closed.iloc[i]
        next_c = closed.iloc[i + 1]

        if direction == "BULLISH":
            # Bullish FVG: prev high < next low
            gap = next_c["low"] - prev["high"]
            if gap >= config.FVG_MIN_SIZE:
                fvgs.append({
                    "top":    next_c["low"],
                    "bottom": prev["high"],
                    "mid":    (next_c["low"] + prev["high"]) / 2,
                    "idx":    i,
                    "time":   curr["time"]
                })

        elif direction == "BEARISH":
            # Bearish FVG: prev low > next high
            gap = prev["low"] - next_c["high"]
            if gap >= config.FVG_MIN_SIZE:
                fvgs.append({
                    "top":    prev["low"],
                    "bottom": next_c["high"],
                    "mid":    (prev["low"] + next_c["high"]) / 2,
                    "idx":    i,
                    "time":   curr["time"]
                })

    # Recent FVGs pehle
    fvgs.reverse()

    if fvgs:
        log_event("INFO", f"{direction} FVGs mily: {len(fvgs)} — "
                          f"Latest: {fvgs[0]['bottom']:.3f}-{fvgs[0]['top']:.3f}")

    return fvgs

# ─────────────────────────────────────────────
#  4. LIQUIDITY LEVELS
# ─────────────────────────────────────────────

def get_liquidity_levels(df, lookback: int = 20) -> dict:
    """
    Recent swing highs aur lows dhundho — yeh liquidity zones hain.
    Price inhe sweep karne aati hai.

    Return:
    {
        "buy_side":  [float, ...]   # Swing highs — buy liquidity
        "sell_side": [float, ...]   # Swing lows  — sell liquidity
    }
    """
    if df is None or len(df) < lookback:
        return {"buy_side": [], "sell_side": []}

    closed = df.iloc[:-1].reset_index(drop=True)
    n      = min(lookback, len(closed) - 2)

    buy_side  = []  # Swing highs
    sell_side = []  # Swing lows

    for i in range(1, n - 1):
        c    = closed.iloc[i]
        prev = closed.iloc[i - 1]
        nxt  = closed.iloc[i + 1]

        if c["high"] > prev["high"] and c["high"] > nxt["high"]:
            buy_side.append(c["high"])

        if c["low"] < prev["low"] and c["low"] < nxt["low"]:
            sell_side.append(c["low"])

    return {"buy_side": buy_side, "sell_side": sell_side}

# ─────────────────────────────────────────────
#  5. PRICE IN ZONE CHECK
# ─────────────────────────────────────────────

def price_in_zone(price: float, zone_top: float, zone_bottom: float,
                  buffer: float = 0.0) -> bool:
    """Price kisi zone ke andar hai?"""
    return (zone_bottom - buffer) <= price <= (zone_top + buffer)
