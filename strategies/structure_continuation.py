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

from datetime import datetime, timezone
import config
from indicators.volatility import calc_atr
from logger import log_event

BUF_GOLD  = 1.2
TP_RR     = 20.0   # far ceiling — asal exit trail_mode se hota hai (trade_manager)

# Strict-mode filters (default OFF = original loose behavior). In se
# structure-continuation ki frequency bohot kam ho jati hai — sirf
# genuine bare moves pe fire karta hai, chhoti/weak pullbacks pe nahi.
# Backtest se tune kiya gaya (90d/180d — loose version quality dilute
# karta tha: expectancy/PF baseline se neeche chala jata tha).
REQUIRE_MIN_SWING   = True
MIN_SWING_ATR_MULT  = 1.5   # structure amplitude (H2-L2) >= ATR * yeh
REQUIRE_SESSION     = True   # sirf London/NY prime session
REQUIRE_H1_ALIGN    = True   # H1 bias bhi trend ke saath aligned ho


def _bias(df, tail_n=10) -> str:
    if df is None or len(df) < tail_n + 2:
        return "NONE"
    closed = df.iloc[:-1]
    ema = closed["close"].tail(tail_n).mean()
    last = closed.iloc[-1]["close"]
    if last > ema:
        return "BULLISH"
    if last < ema:
        return "BEARISH"
    return "NONE"


def _in_session() -> bool:
    h = datetime.now(timezone.utc).hour
    return (config.KILL_ZONE_LONDON_START <= h < config.KILL_ZONE_NY_END)


def _no_trade(symbol=""):
    return {"signal": "NO_TRADE", "symbol": symbol, "entry": 0, "sl": 0,
            "tp1": 0, "tp2": 0, "tp3": 0, "comment": "", "score": 0, "factors": {}}


_LOOKBACK = 200   # sirf recent bars kaafi hain last few pivots ke liye — poori
                  # (growing) history scan karna backtest mein O(n^2) bana deta tha


def _zigzag(df, side_n):
    """Confirmed fractal highs/lows ko strict-alternating zigzag mein reduce karta hai.
    Numpy arrays par (pandas .iloc row-loop nahi — bohot slow hota hai)."""
    closed = df.iloc[:-1].tail(_LOOKBACK).reset_index(drop=True)
    n = len(closed)
    highs = closed["high"].to_numpy()
    lows  = closed["low"].to_numpy()

    raw = []
    for i in range(side_n, n - side_n):
        w_hi = highs[i - side_n:i + side_n + 1]
        w_lo = lows[i - side_n:i + side_n + 1]
        if highs[i] >= w_hi.max() and (w_hi == highs[i]).sum() == 1:
            raw.append((i, "H", highs[i]))
        elif lows[i] <= w_lo.min() and (w_lo == lows[i]).sum() == 1:
            raw.append((i, "L", lows[i]))

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

    swing_amp = None
    if types == ("H", "L", "H", "L"):
        # H1, L1, H2(HH), L2(HL) — continuation break above H2
        h1, l1, h2, l2 = p1, p2, p3, p4
        if h2[2] > h1[2] and l2[2] > l1[2] and last_close > h2[2]:
            sig = "BUY"
            entry = last_close
            sl = l2[2] - BUF_GOLD
            swing_amp = h2[2] - l2[2]

    elif types == ("L", "H", "L", "H"):
        # L1, H1, L2(LL), H2(LH) — continuation break below L2
        l1, h1, l2, h2 = p1, p2, p3, p4
        if l2[2] < l1[2] and h2[2] < h1[2] and last_close < l2[2]:
            sig = "SELL"
            entry = last_close
            sl = h2[2] + BUF_GOLD
            swing_amp = h2[2] - l2[2]

    if sig is None:
        return _no_trade(symbol)

    # ── Strict-mode filters — noise/weak-pullback continuation cut ──
    if REQUIRE_MIN_SWING:
        atr = calc_atr(df.iloc[:-1], period=14)
        if atr <= 0 or swing_amp < atr * MIN_SWING_ATR_MULT:
            return _no_trade(symbol)
    if REQUIRE_SESSION and not _in_session():
        return _no_trade(symbol)
    if REQUIRE_H1_ALIGN:
        h1_bias = _bias(df_h1)
        wanted = "BULLISH" if sig == "BUY" else "BEARISH"
        if h1_bias != wanted:
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
