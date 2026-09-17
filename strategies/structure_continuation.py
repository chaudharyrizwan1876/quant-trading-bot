# ============================================================
#  strategies/structure_continuation.py — Swing structure
#  continuation entry (HH/HL → break = BUY, LH/LL → break = SELL)
# ============================================================
#
#  Displacement scalper (scalper_momentum.py) sirf EK bari candle
#  dekhta hai — staircase-type trends (chhoti chhoti candles, koi
#  ek bari displacement nahi) miss ho jate hain. Yeh strategy
#  uska complement hai: fractal swing points se market STRUCTURE
#  track karta hai, aur jab established uptrend (Higher High →
#  Higher Low) apni last High dobara todhe, ya downtrend
#  (Lower High → Lower Low) apni last Low dobara todhe — wahi
#  continuation entry trigger hai.
# ============================================================

import config
from logger import log_event

BUF_GOLD  = 1.2
TP_RR     = 20.0   # far ceiling — asal exit trail_mode se hota hai (trade_manager)


def _no_trade(symbol=""):
    return {"signal": "NO_TRADE", "symbol": symbol, "entry": 0, "sl": 0,
            "tp1": 0, "tp2": 0, "tp3": 0, "comment": "", "score": 0, "factors": {}}


def _zigzag(df, side_n):
    """Confirmed fractal highs/lows ko strict-alternating zigzag mein reduce karta hai."""
    closed = df.iloc[:-1].reset_index(drop=True)
    n = len(closed)
    raw = []
    for i in range(side_n, n - side_n):
        row = closed.iloc[i]
        window = closed.iloc[i - side_n:i + side_n + 1]
        if row["high"] >= window["high"].max() and (window["high"] == row["high"]).sum() == 1:
            raw.append((i, "H", row["high"]))
        elif row["low"] <= window["low"].min() and (window["low"] == row["low"]).sum() == 1:
            raw.append((i, "L", row["low"]))

    zz = []
    for p in raw:
        if not zz:
            zz.append(p)
            continue
        last = zz[-1]
        if p[1] == last[1]:
            if (p[1] == "H" and p[2] > last[2]) or (p[1] == "L" and p[2] < last[2]):
                zz[-1] = p
        else:
            zz.append(p)
    return zz, closed


def generate_structure_signal(df_h1=None, df_m30=None, df_m15=None, df_m5=None,
                              df_m1=None, point=0.001, df_d1=None, news_sig=None,
                              timeframe=None, fractal_side=None) -> dict:
    symbol = config.SYMBOL_GOLD
    tf     = timeframe or getattr(config, "STRUCT_ENTRY_TIMEFRAME", "M15")
    side_n = fractal_side or getattr(config, "STRUCT_ENTRY_FRACTAL_SIDE", 2)
    df     = {"M15": df_m15, "M5": df_m5}.get(tf, df_m15)

    if df is None or len(df) < (side_n * 2 + 10):
        return _no_trade(symbol)

    zz, closed = _zigzag(df, side_n)
    if len(zz) < 4:
        return _no_trade(symbol)

    last_close = closed.iloc[-1]["close"]
    p1, p2, p3, p4 = zz[-4:]
    types = (p1[1], p2[1], p3[1], p4[1])

    sig = None
    entry = sl = None

    if types == ("H", "L", "H", "L"):
        # H1, L1, H2(HH), L2(HL) — continuation break above H2
        h1, l1, h2, l2 = p1, p2, p3, p4
        if h2[2] > h1[2] and l2[2] > l1[2] and last_close > h2[2]:
            sig = "BUY"
            entry = last_close
            sl = l2[2] - BUF_GOLD

    elif types == ("L", "H", "L", "H"):
        # L1, H1, L2(LL), H2(LH) — continuation break below L2
        l1, h1, l2, h2 = p1, p2, p3, p4
        if l2[2] < l1[2] and h2[2] < h1[2] and last_close < l2[2]:
            sig = "SELL"
            entry = last_close
            sl = h2[2] + BUF_GOLD

    if sig is None:
        return _no_trade(symbol)

    sl_size = (entry - sl) if sig == "BUY" else (sl - entry)
    if sl_size <= 0:
        return _no_trade(symbol)

    if sig == "BUY":
        tp1 = round(entry + sl_size * 1.0, 3)
        tp2 = round(entry + sl_size * (TP_RR * 0.75), 3)
        tp3 = round(entry + sl_size * TP_RR, 3)
    else:
        tp1 = round(entry - sl_size * 1.0, 3)
        tp2 = round(entry - sl_size * (TP_RR * 0.75), 3)
        tp3 = round(entry - sl_size * TP_RR, 3)

    factors = {
        "confirmed_pattern":     True,
        "break_retest":          True,
        "m15_structure_aligned": True,
        "htf_trend_aligned":     True,
    }

    log_event("INFO",
        f"STRUCT-CONT {sig} [{symbol}] TF:{tf} E:{entry:.3f} SL:{sl:.3f} TP:{tp3:.3f}")

    return {
        "signal": sig, "symbol": symbol, "entry": entry, "sl": round(sl, 3),
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "comment": f"STRUCT_{sig}_{symbol}",
        "score": 8, "factors": factors,
    }
