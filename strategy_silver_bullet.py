# ============================================================
#  strategy_silver_bullet.py — Standalone Silver Bullet
#  Gold + Forex — dono ke liye kaam karta hai
#  Gold/ICT/AMD strategies se bilkul ALAG chalti hai
# ============================================================
#
#  CLASSIC ICT SILVER BULLET RULES:
#
#  1. TIME WINDOW — Sirf specific 1-ghante ki windows mein
#     (03-04, 10-11, 14-15 GMT) — inke bahar bilkul kaam nahi
#
#  2. LIQUIDITY SWEEP — Window ke andar price ek recent
#     swing high/low tod kar liquidity le
#
#  3. FVG REVERSAL — Sweep ke turant baad ek Fair Value Gap
#     banti hai OPPOSITE direction mein — yeh asal entry
#     signal hai (institutional reversal confirmation)
#
#  4. ENTRY — FVG ke andar price wapas aaye
#  SL — Sweep ka extreme point + buffer
#  TP — 1:2 minimum (Silver Bullet fast/short trades hoti hain)
# ============================================================

import config
import indicators as ind
from logger import log_event

SWEEP_LOOKBACK = 12    # kitni M5 candles mein sweep dhundho
BUF_GOLD       = 1.5
BUF_FOREX_PIPS = 5


def is_silver_bullet_window() -> bool:
    from datetime import datetime, timezone
    h = datetime.now(timezone.utc).hour
    return any(s <= h < e for s, e in config.SILVER_BULLET_WINDOWS)


def generate_silver_bullet_signal(symbol, df_m5, point) -> dict:
    """
    Standalone Silver Bullet — sirf window ke andar kaam karta hai.
    Liquidity Sweep + FVG reversal — koi baaki condition nahi
    (Kill Zone, BOS, ADX waghera yahan zaroori nahi — yeh apna
    independent, tight rule-set hai).
    """
    no_trade = {"signal":"NO_TRADE","symbol":symbol,"entry":0,"sl":0,
                "tp1":0,"tp2":0,"tp3":0,"comment":""}

    # 1. Time window — sabse pehli aur sabse zaroori shart
    if not is_silver_bullet_window():
        return no_trade

    if df_m5 is None or len(df_m5) < SWEEP_LOOKBACK + 5:
        return no_trade

    closed = df_m5.iloc[:-1].reset_index(drop=True)
    recent = closed.tail(SWEEP_LOOKBACK)
    c      = closed.iloc[-1]   # sabse recent closed candle

    # 2. Liquidity Sweep — recent swing high/low tootna
    prior       = recent.iloc[:-1]
    swing_high  = prior["high"].max()
    swing_low   = prior["low"].min()

    swept_high = c["high"] > swing_high and c["close"] < swing_high
    swept_low  = c["low"]  < swing_low  and c["close"] > swing_low

    trend = None
    sweep_extreme = None

    if swept_low:
        # Neeche liquidity li — reversal upar (BULLISH)
        trend = "BULLISH"
        sweep_extreme = c["low"]
    elif swept_high:
        # Upar liquidity li — reversal neeche (BEARISH)
        trend = "BEARISH"
        sweep_extreme = c["high"]

    if trend is None:
        return no_trade

    log_event("INFO",
        f"SB [{symbol}]: Liquidity sweep detected — Trend={trend}"
    )

    # 3. FVG Reversal check — sweep ke baad turant FVG chahiye
    fvgs = ind.get_fvg(df_m5, trend)
    if not fvgs:
        log_event("INFO", f"SB [{symbol}]: FVG nahi mili — Skip.")
        return no_trade

    fvg = fvgs[0]
    current = df_m5.iloc[-2]["close"]

    # 4. Entry — price FVG ke andar aaye
    if not ind.price_in_zone(current, fvg["top"], fvg["bottom"], 0):
        log_event("INFO", f"SB [{symbol}]: Price FVG mein nahi — Wait.")
        return no_trade

    entry = current

    if "XAU" in symbol.upper():
        buf = BUF_GOLD
    else:
        buf = BUF_FOREX_PIPS * point * 10

    # Minimum SL — sweep entry ke bahut paas ho sakta hai,
    # is liye SKIP karne ki jagah ab WIDEN karte hain (trade
    # cancel nahi hoti, bas SL thoda safe distance tak badhta hai)
    min_sl = BUF_GOLD * 3 if "XAU" in symbol.upper() else BUF_FOREX_PIPS * point * 10 * 2

    if trend == "BULLISH":
        sl = sweep_extreme - buf
        sl_size = entry - sl
        if sl_size <= 0:
            return no_trade
        if sl_size < min_sl:
            log_event("INFO",
                f"SB [{symbol}]: SL tight tha ({sl_size:.3f}) — "
                f"minimum ({min_sl:.3f}) tak widen kar raha hoon."
            )
            sl_size = min_sl
            sl = entry - sl_size
        tp1 = entry + sl_size * 1.0
        tp2 = entry + sl_size * 2.0
        tp3 = entry + sl_size * 2.0   # Silver Bullet — fast trade, 1:2 target
        sig = "BUY"
    else:
        sl = sweep_extreme + buf
        sl_size = sl - entry
        if sl_size <= 0:
            return no_trade
        if sl_size < min_sl:
            log_event("INFO",
                f"SB [{symbol}]: SL tight tha ({sl_size:.3f}) — "
                f"minimum ({min_sl:.3f}) tak widen kar raha hoon."
            )
            sl_size = min_sl
            sl = entry + sl_size
        tp1 = entry - sl_size * 1.0
        tp2 = entry - sl_size * 2.0
        tp3 = entry - sl_size * 2.0
        sig = "SELL"

    comment = f"SB_{sig}_{symbol}_STANDALONE"
    log_event("INFO",
        f"SILVER BULLET {sig} [{symbol}] E:{entry:.5f} SL:{sl:.5f} TP:{tp3:.5f}"
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
        "score":   8   # AMD (10) se thoda kam — kyunki SB fast/short trade hai
    }
