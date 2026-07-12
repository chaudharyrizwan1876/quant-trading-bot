# ============================================================
#  strategy_amd.py — Standalone AMD (Power of 3) Strategy
#  Gold + Forex — dono ke liye kaam karta hai
#  Gold/ICT strategies se bilkul ALAG chalti hai
# ============================================================
#
#  PROFESSIONAL AMD LOGIC (50+ saal ka trading experience):
#
#  1. ACCUMULATION — Price ek tight range mein consolidate
#     karti hai (institutions positions build karte hain)
#
#  2. MANIPULATION — Range se bahar ek fake move (liquidity
#     grab) hota hai — retail traders ko galat direction
#     mein phasaya jata hai
#
#  3. DISTRIBUTION — Asal move shuru hota hai — manipulation
#     ke opposite direction mein — yeh institutional move hai
#
#  ENTRY RULE:
#     Distribution confirm hone ke baad — price range ke
#     opposite edge tod kar close ho (real breakout)
#
#  SL RULE:
#     Manipulation ka extreme point (wahan invalidate hota
#     hai pattern) + buffer — yeh sabse logical SL hai
#     kyunki agar price wahan wapas jaye to pattern galat tha
#
#  TP RULE:
#     Measured move — accumulation range ki size ko
#     breakout point se project karo (classic AMD target)
#     Minimum 1:2, capped analysis ke through
# ============================================================

import config
from logger import log_event

AMD_LOOKBACK   = 15
MIN_RANGE_MULT = 0.6   # Accumulation range kam se kam itni tight ho
BUF_GOLD       = 1.5   # $ buffer Gold SL ke liye
BUF_FOREX_PIPS = 5      # pips buffer Forex SL ke liye

_state = {}   # {symbol: {"phase":..., "acc_high":..., "acc_low":..., ...}}


def generate_amd_signal(symbol, df_m15, point) -> dict:
    """
    Standalone AMD signal — Gold/ICT strategies se independent.
    Sirf jab poora AMD pattern professional criteria pura kare
    tab trade deta hai.
    """
    no_trade = {"signal":"NO_TRADE","symbol":symbol,"entry":0,"sl":0,
                "tp1":0,"tp2":0,"tp3":0,"comment":""}

    if df_m15 is None or len(df_m15) < AMD_LOOKBACK + 5:
        return no_trade

    closed = df_m15.iloc[:-1].tail(AMD_LOOKBACK).reset_index(drop=True)
    n = len(closed)
    if n < 12:
        return no_trade

    third = n // 3
    acc  = closed.iloc[:third]
    manp = closed.iloc[third:2*third]
    dist = closed.iloc[2*third:]

    acc_high = acc["high"].max()
    acc_low  = acc["low"].min()
    acc_range = acc_high - acc_low
    avg_range = (closed["high"] - closed["low"]).mean()

    if avg_range <= 0:
        return no_trade

    # ── 1. ACCUMULATION check — tight range zaroori ──
    is_tight = acc_range < avg_range * third * MIN_RANGE_MULT
    if not is_tight:
        return no_trade

    # ── 2. MANIPULATION check — dono direction try karo ──
    manip_high = manp["high"].max()
    manip_low  = manp["low"].min()

    bullish_manip = manip_low  < acc_low    # Neeche fake breakdown
    bearish_manip = manip_high > acc_high   # Upar fake breakout

    # ── 3. DISTRIBUTION check — asal move confirm ──
    dist_close = dist.iloc[-1]["close"]
    dist_open  = dist.iloc[0]["open"]

    trend = None

    if bullish_manip and not bearish_manip:
        # Manipulation neeche thi — distribution upar honi chahiye
        if dist_close > acc_high and dist_close > dist_open:
            trend = "BULLISH"

    elif bearish_manip and not bullish_manip:
        # Manipulation upar thi — distribution neeche honi chahiye
        if dist_close < acc_low and dist_close < dist_open:
            trend = "BEARISH"

    if trend is None:
        return no_trade

    log_event("INFO",
        f"AMD [{symbol}]: Pattern confirmed! Trend={trend} "
        f"AccRange:{acc_low:.5f}-{acc_high:.5f}"
    )

    # ── ENTRY, SL, TP — Professional Rules ──
    entry = dist_close

    if "XAU" in symbol.upper():
        buf = BUF_GOLD
    else:
        buf = BUF_FOREX_PIPS * point * 10

    if trend == "BULLISH":
        sl = manip_low - buf              # Manipulation extreme + buffer
        sl_size = entry - sl
        if sl_size <= 0:
            return no_trade

        # BUG FIX: Ab hamesha pure RR-based TP — measured move wala
        # buggy "min()" logic hataya jo galti se chota TP bana raha tha
        tp1 = entry + sl_size * 1.0
        tp2 = entry + sl_size * 2.0
        tp3 = entry + sl_size * config.RR_FINAL   # 1:3 guaranteed

        sig = "BUY"

    else:
        sl = manip_high + buf
        sl_size = sl - entry
        if sl_size <= 0:
            return no_trade

        tp1 = entry - sl_size * 1.0
        tp2 = entry - sl_size * 2.0
        tp3 = entry - sl_size * config.RR_FINAL   # 1:3 guaranteed

        sig = "SELL"

    # Minimum SL sanity check
    min_sl = BUF_GOLD * 3 if "XAU" in symbol.upper() else BUF_FOREX_PIPS * point * 10 * 2
    if sl_size < min_sl:
        log_event("INFO", f"AMD [{symbol}]: SL too tight — Skip.")
        return no_trade

    comment = f"AMD_{sig}_{symbol}_STANDALONE"
    log_event("INFO",
        f"AMD {sig} [{symbol}] E:{entry:.5f} SL:{sl:.5f} "
        f"TP1:{tp1:.5f} TP3:{tp3:.5f}"
    )

    return {
        "signal":  sig,
        "symbol":  symbol,
        "entry":   entry,
        "sl":      sl,
        "tp1":     tp1,
        "tp2":     tp2,
        "tp3":     tp3,
        "comment": comment,
        "score":   10   # AMD apna fixed high-confidence score deta hai
    }
