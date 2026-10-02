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
#
#  EARLY TRIGGER (optional): purana behavior displacement candle ke
#  pure CLOSE hone ka wait karta tha — jab tak bot react karta, price
#  pehle hi candle ke end/low tak ja chuki hoti thi (poora move miss).
#  Early-trigger mode M1 candles se abhi BAN RAHI (forming) M5 candle
#  ko on-the-fly build karta hai aur usi par displacement check karta
#  hai — candle ke beech mein hi entry, zyada room milta hai.
# ============================================================

from datetime import datetime, timezone
import config
from indicators.volatility import calc_atr
from logger import log_event

# Backtest-optimized defaults. TP_RR=4.0 validated on 6mo train/test split
# (Feb-Jun optimize / Jun-Aug validate): improves BOTH periods vs TP3
# (train -0.3R→+4.4R, test +7.2R→+17.8R PF1.19, full-6mo +7R→+22R). Higher
# TP is regime-robust here because SL locks +1R at 2R profit — reversing
# trades pay the same either way, so a far TP only harvests full trend runs
# (asymmetric: loss capped 1R, winners ~4R). WR stays ~35% across TP values.
# CAVEAT: edge is modest & regime-dependent (train PF ~1.02) — demo only.
DISPLACEMENT_BODY_MULT = 2.5    # body avg-body se itni guna bari ho
MAX_OPP_WICK_RATIO     = 0.35   # opposite wick range ka itne se kam
VOL_SPIKE_MULT         = 1.3
BUF_GOLD               = 1.2
MIN_SL_GOLD            = 1.5
# TP ab door ka safety ceiling hai — asal exit progressive TRAIL karti
# hai (config.TRAIL_MODE="giveback"). Trail bade trend ride karti hai,
# tp3 sirf ek hard cap. Backtest 6mo: trailing ne full +22R→+39R kiya.
TP_RR                  = 20.0   # far TP ceiling (trail decides exit)

# Optional strict filters (default OFF = current behavior). Backtest se
# tune karne ke liye — live config in se override ho sakta hai.
REQUIRE_M15_ALIGN = False   # sirf M15 bias ke saath trade (counter-trend cut)
REQUIRE_SESSION   = False   # sirf London/NY session mein trade

# ── Early-trigger (intrabar) mode ──
# Backtest (14d/30d/90d — max available M1 history on this broker):
# closed-candle +27.85R → early-trigger +62.09R (90d), PF 1.21→1.42,
# drawdown 14.39R→10.72R, consistent improvement across all 3 windows.
# Purana "wait for candle close" behavior candle ke END tak entry
# delay karta tha (move ka best hissa chhoot jata tha) — ab displacement
# candle ke BEECH mein hi (M1 se forming M5 candle reconstruct karke)
# entry milti hai.
EARLY_TRIGGER_ENABLED   = True
EARLY_TRIGGER_MIN_M1    = 2     # forming M5 candle mein kam-se-kam itni M1 bars ban chuki hon
EARLY_TRIGGER_BODY_MULT = DISPLACEMENT_BODY_MULT   # partial body ke liye wahi threshold


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


def _forming_m5_bucket(df_m1):
    """Abhi ban rahi (incomplete) M5 candle ko M1 bars se on-the-fly
    reconstruct karta hai — displacement candle ke pure close hone ka
    wait kiye baghair uska partial shape dekhne ke liye."""
    if df_m1 is None or len(df_m1) < 2:
        return None
    m1_closed = df_m1.iloc[:-1]   # M1 ki apni forming candle exclude
    if len(m1_closed) < 2:
        return None
    now = datetime.now(timezone.utc)
    bucket_start = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    times = m1_closed["time"]
    # Live mt5_connector.get_candles naive timestamps deta hai (utc=True
    # nahi), backtest cache tz-aware — dono ke saath compare match karo
    # warna "Invalid comparison between dtype=datetime64[s] and datetime".
    if getattr(times.dt, "tz", None) is None:
        bucket_start = bucket_start.replace(tzinfo=None)
    bucket = m1_closed[times >= bucket_start]
    if len(bucket) < EARLY_TRIGGER_MIN_M1:
        return None
    return {
        "open":  bucket.iloc[0]["open"],
        "high":  bucket["high"].max(),
        "low":   bucket["low"].min(),
        "close": bucket.iloc[-1]["close"],
        "tick_volume": bucket["tick_volume"].sum() if "tick_volume" in bucket.columns else None,
    }


def _check_displacement(candle, avg_body, avg_vol, body_mult):
    """candle: dict-like (open/high/low/close/[tick_volume]). Common
    displacement+opp-wick+volume check — closed candle aur forming
    (early-trigger) candle dono ke liye reuse hota hai."""
    body = abs(candle["close"] - candle["open"])
    rng  = max(candle["high"] - candle["low"], 1e-9)

    if body < avg_body * body_mult:
        return None

    if candle["close"] > candle["open"]:
        trend = "BULLISH"
        opp_wick = (candle["high"] - candle["close"]) / rng
    else:
        trend = "BEARISH"
        opp_wick = (candle["close"] - candle["low"]) / rng
    if opp_wick > MAX_OPP_WICK_RATIO:
        return None

    vol_ok = True
    if candle.get("tick_volume") is not None and avg_vol is not None:
        vol_ok = avg_vol <= 0 or candle["tick_volume"] >= avg_vol * VOL_SPIKE_MULT
    if not vol_ok:
        return None

    return trend, body, vol_ok


def _build_signal(symbol, trend, entry, sl_hi, sl_lo, body, avg_body,
                  vol_ok, df_m15, tag):
    if trend == "BULLISH":
        sl = sl_lo - BUF_GOLD
        sl_size = entry - sl
    else:
        sl = sl_hi + BUF_GOLD
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
        f"SCALP-MOM{tag} {sig} [{symbol}] E:{entry:.3f} SL:{sl:.3f} "
        f"TP:{tp3:.3f} body:{body:.2f}/{avg_body:.2f} bias:{bias}")

    return {
        "signal": sig, "symbol": symbol, "entry": entry, "sl": round(sl, 3),
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "comment": f"SCALP_MOM{tag}_{sig}_{symbol}",
        "score": 8, "factors": factors,
    }


def generate_scalp_momentum_signal(df_h1=None, df_m30=None, df_m15=None,
                                   df_m5=None, df_m1=None, point=0.001,
                                   df_d1=None, news_sig=None) -> dict:
    symbol = config.SYMBOL_GOLD
    if df_m5 is None or len(df_m5) < 25:
        return _no_trade(symbol)

    closed = df_m5.iloc[:-1].reset_index(drop=True)
    avg_body = (closed["close"] - closed["open"]).abs().tail(20).mean()
    if avg_body <= 0:
        return _no_trade(symbol)
    avg_vol = closed["tick_volume"].tail(20).mean() if "tick_volume" in closed.columns else None

    # ── Early trigger: abhi ban rahi M5 candle par (M1 se reconstruct) —
    #    displacement candle ke pure close hone ka wait nahi karte, is
    #    liye entry candle ke beech mein milti hai, uske end pe nahi.
    if EARLY_TRIGGER_ENABLED:
        forming = _forming_m5_bucket(df_m1)
        if forming is not None:
            result = _check_displacement(forming, avg_body, avg_vol, EARLY_TRIGGER_BODY_MULT)
            if result is not None:
                trend, body, vol_ok = result
                entry = forming["close"]
                return _build_signal(symbol, trend, entry,
                                     forming["high"], forming["low"],
                                     body, avg_body, vol_ok, df_m15, "-EARLY")

    # ── Fallback / default: purana behavior — pure closed candle par ──
    c = closed.iloc[-1]
    result = _check_displacement(c, avg_body, avg_vol, DISPLACEMENT_BODY_MULT)
    if result is None:
        return _no_trade(symbol)
    trend, body, vol_ok = result

    entry = df_m5.iloc[-2]["close"]
    return _build_signal(symbol, trend, entry, c["high"], c["low"],
                         body, avg_body, vol_ok, df_m15, "")
