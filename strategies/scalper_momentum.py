# ============================================================
#  strategies/scalper_momentum.py — M1/M5 Momentum/Breakout Scalper
# ============================================================
#
#  Alag philosophy (ICT sweep se ulta):
#    * Setup: M5 par ek DISPLACEMENT candle — body avg se kaafi
#      bari, chota opposite wick, volume spike ke saath. Yeh
#      institutional conviction dikhati hai → us direction mein
#      CONTINUATION scalp.
#    * Context: M15 bias aligned ho to zyada confidence (factor).
#    * SL: displacement candle ke opposite end ke bahar (tight).
#    * TP: 1:1.5 / 1:2 (fast). Time-stop live config se.
#
#  Risk: choppy/ranging market mein fake breakouts → isi liye
#  volume spike + body-ratio strict rakhe hain, aur confidence
#  gate marginal setups filter karega.
# ============================================================

from datetime import datetime, timezone
import config
from indicators.volatility import calc_atr
from logger import log_event

# Backtest-optimized defaults (60d full-engine grid, gap-fixed simulator):
# displacement 2.5 + TP 1:3 + 90min time-stop → best RISK-ADJUSTED result:
# +13.86R, PF 1.15, drawdown 12.55R, 202 trades (vs d2.0 = +16.95R but 18R DD).
# Sabse strong reliable pattern: TP 1:3 >> 1:2 (Gold trends → winners run).
# NOTE: recommended MAX_HOLD_MINUTES=90 (config) is pairs with this.
DISPLACEMENT_BODY_MULT = 2.5    # body avg-body se itni guna bari ho
MAX_OPP_WICK_RATIO     = 0.35   # opposite wick range ka itne se kam
VOL_SPIKE_MULT         = 1.3
BUF_GOLD               = 1.2
MIN_SL_GOLD            = 1.5
TP_RR                  = 3.0    # final TP (tp3) = itne R (Gold trends → let run)

# Optional strict filters (default OFF = current behavior). Backtest se
# tune karne ke liye — live config in se override ho sakta hai.
REQUIRE_M15_ALIGN = False   # sirf M15 bias ke saath trade (counter-trend cut)
REQUIRE_SESSION   = False   # sirf London/NY session mein trade


def _no_trade(symbol=""):
    return {"signal": "NO_TRADE", "symbol": symbol, "entry": 0, "sl": 0,
            "tp1": 0, "tp2": 0, "tp3": 0, "comment": "", "score": 0, "factors": {}}


def _m15_bias(df_m15) -> str:
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


def generate_scalp_momentum_signal(df_h1=None, df_m30=None, df_m15=None,
                                   df_m5=None, df_m1=None, point=0.001,
                                   df_d1=None, news_sig=None) -> dict:
    symbol = config.SYMBOL_GOLD
    if df_m5 is None or len(df_m5) < 25:
        return _no_trade(symbol)

    closed = df_m5.iloc[:-1].reset_index(drop=True)
    c = closed.iloc[-1]

    avg_body = (closed["close"] - closed["open"]).abs().tail(20).mean()
    if avg_body <= 0:
        return _no_trade(symbol)

    body = abs(c["close"] - c["open"])
    rng  = max(c["high"] - c["low"], 1e-9)

    # Displacement check
    if body < avg_body * DISPLACEMENT_BODY_MULT:
        return _no_trade(symbol)

    if c["close"] > c["open"]:
        trend = "BULLISH"
        opp_wick = (c["high"] - c["close"]) / rng
    else:
        trend = "BEARISH"
        opp_wick = (c["close"] - c["low"]) / rng
    if opp_wick > MAX_OPP_WICK_RATIO:
        return _no_trade(symbol)

    # Volume spike (agar data ho)
    vol_ok = True
    if "tick_volume" in closed.columns:
        avg_vol = closed["tick_volume"].tail(20).mean()
        vol_ok = avg_vol <= 0 or c["tick_volume"] >= avg_vol * VOL_SPIKE_MULT
    if not vol_ok:
        return _no_trade(symbol)

    entry = df_m5.iloc[-2]["close"]

    # SL: displacement candle ke opposite end ke bahar
    if trend == "BULLISH":
        sl = min(c["low"], c["open"]) - BUF_GOLD
        sl_size = entry - sl
    else:
        sl = max(c["high"], c["open"]) + BUF_GOLD
        sl_size = sl - entry

    if sl_size < MIN_SL_GOLD:
        sl_size = MIN_SL_GOLD
        sl = entry - sl_size if trend == "BULLISH" else entry + sl_size
    if sl_size <= 0:
        return _no_trade(symbol)

    if trend == "BULLISH":
        tp1 = round(entry + sl_size * 1.0, 3)
        tp2 = round(entry + sl_size * (TP_RR * 0.75), 3)
        tp3 = round(entry + sl_size * TP_RR, 3)
        sig = "BUY"
    else:
        tp1 = round(entry - sl_size * 1.0, 3)
        tp2 = round(entry - sl_size * (TP_RR * 0.75), 3)
        tp3 = round(entry - sl_size * TP_RR, 3)
        sig = "SELL"

    bias = _m15_bias(df_m15)
    session_ok = _in_session()

    # Optional strict filters (backtest tuning)
    if REQUIRE_M15_ALIGN and bias != trend:
        return _no_trade(symbol)
    if REQUIRE_SESSION and not session_ok:
        return _no_trade(symbol)

    factors = {
        "confirmed_pattern":     True,
        "m5_confirmation":       True,
        "volume_confirmation":   vol_ok,
        "m15_structure_aligned": (bias == trend),
        "htf_trend_aligned":     (bias == trend),
        "prime_session":         session_ok,
    }

    log_event("INFO",
        f"SCALP-MOM {sig} [{symbol}] E:{entry:.3f} SL:{sl:.3f} "
        f"TP:{tp3:.3f} body:{body:.2f}/{avg_body:.2f} bias:{bias}")

    return {
        "signal": sig, "symbol": symbol, "entry": entry, "sl": round(sl, 3),
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "comment": f"SCALP_MOM_{sig}_{symbol}",
        "score": 8, "factors": factors,
    }
