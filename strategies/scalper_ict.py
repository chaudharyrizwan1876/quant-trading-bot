# ============================================================
#  strategies/scalper_ict.py — M1/M5 ICT Liquidity-Sweep Scalper
# ============================================================
#
#  Asal scalper (swing-hybrid gold_hybrid se ALAG):
#    * Decision timeframe = M5 (fills M1), context = M15
#    * Koi H1/M30 trend-following majority vote NAHI — yeh fast,
#      reactive hai. M15 bias sirf ek bonus factor hai, block nahi.
#    * Setup: recent M5 swing high/low ka LIQUIDITY SWEEP (wick se
#      break + wapas andar close) → reversal direction mein entry.
#      FVG ya strong reversal candle confirmation.
#    * SL: sweep extreme ke thoda bahar (TIGHT — scalp SL).
#    * TP: 1:1.5 aur 1:2 (fast). Time-stop live config se aata hai.
#
#  Signature gold_hybrid jaisi hai taake backtest engine + main.py
#  dono use kar saken.
# ============================================================

from datetime import datetime, timezone
import config
import indicators as ind
from indicators.volatility import calc_atr
from logger import log_event

SWEEP_LOOKBACK = 12     # kitni M5 candles mein swing dhundho
BUF_GOLD       = 1.2    # $ buffer SL ke liye
MIN_SL_GOLD    = 1.5    # $ minimum scalp SL


def _no_trade(symbol=""):
    return {"signal": "NO_TRADE", "symbol": symbol, "entry": 0, "sl": 0,
            "tp1": 0, "tp2": 0, "tp3": 0, "comment": "", "score": 0, "factors": {}}


def _m15_bias(df_m15) -> str:
    """Halka M15 bias — sirf factor ke liye (block nahi karta)."""
    if df_m15 is None or len(df_m15) < 12:
        return "NONE"
    closed = df_m15.iloc[:-1]
    ema = closed["close"].tail(10).mean()
    last = closed.iloc[-1]["close"]
    if last > ema:
        return "BULLISH"
    if last < ema:
        return "BEARISH"
    return "NONE"


def _in_session() -> bool:
    h = datetime.now(timezone.utc).hour
    return (config.KILL_ZONE_LONDON_START <= h < config.KILL_ZONE_NY_END)


def generate_scalp_ict_signal(df_h1=None, df_m30=None, df_m15=None,
                              df_m5=None, df_m1=None, point=0.001,
                              df_d1=None, news_sig=None) -> dict:
    symbol = config.SYMBOL_GOLD
    if df_m5 is None or len(df_m5) < SWEEP_LOOKBACK + 5:
        return _no_trade(symbol)

    closed = df_m5.iloc[:-1].reset_index(drop=True)
    recent = closed.tail(SWEEP_LOOKBACK)
    prior  = recent.iloc[:-1]
    c      = closed.iloc[-1]

    swing_high = prior["high"].max()
    swing_low  = prior["low"].min()

    swept_low  = c["low"]  < swing_low  and c["close"] > swing_low   # bullish
    swept_high = c["high"] > swing_high and c["close"] < swing_high  # bearish

    trend = None
    sweep_extreme = None
    if swept_low:
        trend, sweep_extreme = "BULLISH", c["low"]
    elif swept_high:
        trend, sweep_extreme = "BEARISH", c["high"]
    if trend is None:
        return _no_trade(symbol)

    # Reversal confirmation: FVG (M5) ya strong reversal candle
    fvgs = ind.get_fvg(df_m5, trend)
    has_fvg = bool(fvgs)
    body = abs(c["close"] - c["open"])
    rng  = max(c["high"] - c["low"], 1e-9)
    reversal_candle = (
        (trend == "BULLISH" and c["close"] > c["open"] and body / rng > 0.4) or
        (trend == "BEARISH" and c["close"] < c["open"] and body / rng > 0.4)
    )
    if not (has_fvg or reversal_candle):
        return _no_trade(symbol)

    entry = df_m5.iloc[-2]["close"]

    # ── SL: sweep extreme ke thoda bahar (tight) ──
    if trend == "BULLISH":
        sl = sweep_extreme - BUF_GOLD
        sl_size = entry - sl
    else:
        sl = sweep_extreme + BUF_GOLD
        sl_size = sl - entry

    if sl_size < MIN_SL_GOLD:
        sl_size = MIN_SL_GOLD
        sl = entry - sl_size if trend == "BULLISH" else entry + sl_size

    if sl_size <= 0:
        return _no_trade(symbol)

    if trend == "BULLISH":
        tp1 = round(entry + sl_size * 1.0, 3)
        tp2 = round(entry + sl_size * 1.5, 3)
        tp3 = round(entry + sl_size * 2.0, 3)
        sig = "BUY"
    else:
        tp1 = round(entry - sl_size * 1.0, 3)
        tp2 = round(entry - sl_size * 1.5, 3)
        tp3 = round(entry - sl_size * 2.0, 3)
        sig = "SELL"

    bias = _m15_bias(df_m15)
    session_ok = _in_session()

    factors = {
        "liquidity_sweep":       True,
        "confirmed_pattern":     True,
        "fair_value_gap":        has_fvg,
        "m5_confirmation":       reversal_candle,
        "m15_structure_aligned": (bias == trend),
        "htf_trend_aligned":     (bias == trend),
        "prime_session":         session_ok,
    }

    log_event("INFO",
        f"SCALP-ICT {sig} [{symbol}] E:{entry:.3f} SL:{sl:.3f} "
        f"TP:{tp3:.3f} FVG:{has_fvg} bias:{bias}")

    return {
        "signal": sig, "symbol": symbol, "entry": entry, "sl": round(sl, 3),
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "comment": f"SCALP_ICT_{sig}_{symbol}",
        "score": 8, "factors": factors,
    }
