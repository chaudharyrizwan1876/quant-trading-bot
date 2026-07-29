# ============================================================
#  strategy_gold.py — Gold Strategy V7.3
#  NEW: Pre-London/Pre-NY sessions, Silver Bullet standalone
#       window, AMD (Accumulation-Manipulation-Distribution)
# ============================================================

from datetime import datetime, timezone
import config
import indicators as ind
from logger import log_event

MIN_SL, MAX_SL = 8.0, 30.0
BUF = 2.0
MIN_SCORE = 6
ATR_PERIOD = 14


def generate_gold_signal(df_h1, df_m30, df_m15, df_m5, df_m1, point,
                         df_d1=None, news_sig=None) -> dict:
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,
                "tp3":0,"comment":"","score":0}

    if _is_weekend():
        log_event("INFO","GOLD: Weekend — No trade."); return no_trade
    if _is_friday_cutoff():
        log_event("INFO","GOLD: Friday cutoff."); return no_trade

    # V7.5: Session ab BLOCKING nahi — bonus hai
    session = _get_session()
    if session:
        log_event("INFO", f"GOLD: Session={session} (bonus milega)")
    else:
        session = "OFF_SESSION"
        log_event("INFO", "GOLD: Off-session — trade phir bhi possible (no bonus).")

    trend = _get_trend_bos(df_h1, df_m30, df_m15)
    if trend == "NONE":
        log_event("INFO","GOLD: BOS trend unclear."); return no_trade

    log_event("INFO", f"GOLD: Trend={trend} Session={session}")

    # M15 ka structure ab sirf INFO/bonus ke liye — majority vote
    # mein M15 ka vote already shamil ho chuka hai, isliye ab
    # yahan hard-block nahi karte (pehle yeh poori move miss
    # karwa deta tha jab H1 lag kar raha hota tha).
    m15_struct = ind.get_market_structure(df_m15)
    m15_trend  = m15_struct["trend"]
    if m15_trend != "NONE" and m15_trend != trend:
        log_event("INFO", f"GOLD: M15={m15_trend} vs Trend={trend} — mismatch (info only, no block).")

    if not _check_adx(df_m15):
        log_event("INFO","GOLD: ADX low — ranging."); return no_trade

    current = df_m15.iloc[-2]["close"] if df_m15 is not None else 0
    if not _check_d1_levels(df_d1, trend, current):
        return no_trade

    # V8.4 FIX: RSI momentum check ab BLOCK nahi karta — bahut
    # zyada trades cancel kar raha tha. Sirf info ke liye log
    # hota hai ab, koi effect nahi score/entry pe.
    _log_momentum_info(df_h1, trend)

    news_dir = None
    if config.NEWS_TRADE_ENABLED and news_sig and \
            news_sig.get("signal") != "NO_TRADE":
        news_dir = news_sig["signal"]
        expected = "BUY" if trend == "BULLISH" else "SELL"
        if news_dir != expected: news_dir = None

    # V8.2: Institutional Footprint zone PEHLE try karo (priority)
    # Agar milta hai to normal OB/FVG check bilkul skip karo —
    # yeh sabse high-confidence setup hai (retail SL le liya gaya).
    m15_zone = _find_institutional_zone(df_h1, df_m15, trend, point)
    is_institutional = m15_zone is not None

    if not m15_zone:
        # Fallback — purana OB/FVG/LIQ system (frequency maintain rakhne ke liye)
        m15_zone = _find_m15_zone(df_m15, trend)
        if m15_zone and not _is_ote_entry(current, m15_zone, trend):
            log_event("INFO", "GOLD: OTE deep nahi — Wait.")
            m15_zone = None

    # V7.4: Break-Retest ab BONUS hai, mandatory nahi
    # Retest mil jaye to extra score — na mile to bhi trade ho sakti hai
    retest_ok = False
    if m15_zone:
        retest_ok = check_break_retest(df_m15, trend, m15_zone)
        if not retest_ok:
            log_event("INFO", "GOLD: Retest abhi nahi — bonus na milega, aage badho.")

    m5_confirm = _m5_confirm(df_m5, trend)

    # V8.3 FIX: M1 trigger ab BONUS hai, mandatory nahi (jaisa
    # Break-Retest pehle se hai) — sirf 2-candle M1 pattern na
    # milne ki wajah se poori trade cancel nahi hogi ab.
    m1_trigger = _m1_entry_confirmed(df_m1, trend)
    if not m1_trigger:
        log_event("INFO", "GOLD: M1 confirm nahi — bonus na milega, aage badho.")

    # V7.3: AMD bonus check
    amd_ok = _check_amd(df_m15, trend)

    # V8.1 IMPROVEMENT 2: Volume confirmation
    volume_ok = _check_volume(df_m15)

    # V8.1 IMPROVEMENT 3: Daily pivot bonus
    pivots = _calc_pivots(df_d1)
    pivot_ok = _check_pivot_bonus(current, trend, pivots)

    # V8.1 IMPROVEMENT 5: ATR regime caution
    atr_abnormal = _check_atr_regime(df_m15)

    judas_ok = _is_judas_swing_window()
    score = _calc_score(trend, m15_trend, m15_zone, m5_confirm,
                        m1_trigger, news_dir, session, amd_ok,
                        volume_ok, pivot_ok, atr_abnormal,
                        is_institutional, judas_ok)
    if retest_ok:
        score += 3   # Retest confirm bonus

    # V8.1 IMPROVEMENT 1: Weekly Quota Fallback — threshold relax karo
    quota_adj  = _get_quota_adjustment()
    min_score  = MIN_SCORE + quota_adj   # quota_adj negative hota hai

    # V8.1 IMPROVEMENT 6: Hour-of-day adaptive learning (optional hook)
    try:
        from memory import trade_memory as tm
        hour_adj = tm.get_hour_adaptive_score(config.SYMBOL_GOLD)
        score += hour_adj
    except Exception:
        pass

    log_event("INFO",
        f"GOLD: Score={score}/{min_score} (base_min={MIN_SCORE} quota_adj={quota_adj}) "
        f"AMD={amd_ok} Retest={retest_ok} Vol={volume_ok} Pivot={pivot_ok} ATR_abn={atr_abnormal}"
    )
    if score < min_score:
        log_event("INFO", f"GOLD: Score low — Skip."); return no_trade

    # V8.3 FIX: entry_ok ab M1 trigger pe depend nahi karta —
    # sirf zone (ya news) chahiye. M1 sirf score ke through
    # confidence badhata hai, block nahi karta.
    zone_ok  = m15_zone is not None
    entry_ok = zone_ok or news_dir is not None
    if not entry_ok:
        log_event("INFO","GOLD: Entry conditions fail — koi zone/news nahi."); return no_trade

    entry = df_m1.iloc[-2]["close"] if df_m1 is not None and len(df_m1)>2 \
            else current
    zone_type = m15_zone["type"] if m15_zone else "NEWS"
    if news_dir: zone_type += "_NEWS"
    if amd_ok:   zone_type += "_AMD"

    sl_info = _calc_sl_atr(df_m15, trend, entry)
    if sl_info is None:
        log_event("INFO","GOLD: SL invalid."); return no_trade
    sl, sl_size = sl_info["sl"], sl_info["size"]
    log_event("INFO", f"GOLD: SL={sl:.3f} Size=${sl_size:.2f}")

    if trend == "BULLISH":
        tp1 = round(entry + sl_size*1.0, 3)
        tp2 = round(entry + sl_size*2.0, 3)
        # V8.1 IMPROVEMENT 4: Structure-based TP (draw on liquidity)
        tp3 = round(_find_liquidity_target(df_h1, entry, trend, sl_size, config.RR_FINAL), 3)
        sig = "BUY"
    else:
        tp1 = round(entry - sl_size*1.0, 3)
        tp2 = round(entry - sl_size*2.0, 3)
        tp3 = round(_find_liquidity_target(df_h1, entry, trend, sl_size, config.RR_FINAL), 3)
        sig = "SELL"

    # Weekly quota counter update — is signal ne threshold pass kiya
    _record_weekly_signal()

    # ── Structured factors for the confidence engine (ai/confidence.py) ──
    # Yeh wahi booleans hain jo upar already compute ho chuke hain —
    # ab inhe ek normalized dict mein expose karte hain taake decision
    # layer inka weighted, explainable evaluation kar sake.
    zt = m15_zone["type"] if m15_zone else ""
    factors = {
        "htf_trend_aligned":     trend != "NONE",
        "m15_structure_aligned": m15_trend == trend,
        "institutional_sweep":   is_institutional or "INST_SWEEP" in zt,
        "order_block":           "OB" in zt,
        "fair_value_gap":        "FVG" in zt,
        "liquidity_sweep":       "LIQ" in zt,
        "break_retest":          bool(retest_ok),
        "m5_confirmation":       bool(m5_confirm),
        "m1_trigger":            bool(m1_trigger),
        "amd_pattern":           bool(amd_ok),
        "volume_confirmation":   bool(volume_ok),
        "pivot_confluence":      bool(pivot_ok),
        "prime_session":         session in ("LONDON", "NEW_YORK"),
        "silver_bullet_window":  session == "SILVER_BULLET",
        "judas_window":          bool(judas_ok),
        "news_aligned":          news_dir is not None,
        "atr_abnormal":          bool(atr_abnormal),
    }

    log_event("INFO",
        f"GOLD {sig} E:{entry:.3f} SL:{sl:.3f} TP1:{tp1:.3f} "
        f"TP2:{tp2:.3f} TP3:{tp3:.3f} Score:{score}")
    return {"signal":sig,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
            "comment":f"GOLD_{sig}_{zone_type}_S{score}","score":score,
            "factors":factors}


# ─────────────────────────────────────────────
#  V7.3: SESSION — Pre-London, London, Pre-NY, NY, Silver Bullet
# ─────────────────────────────────────────────

def _get_session() -> str:
    """
    BUG FIX: Pehle yahan hardcoded 8-12/13-17 tha jo config.py
    ke actual values (7-12 / 12-17) se match nahi karta tha —
    isse ek 1-ghante ka GAP (12:00-13:00 GMT) ban gaya tha
    jahan koi session match nahi hota tha. Ab config se
    directly values liye ja rahe hain — koi gap nahi.
    """
    h = datetime.now(timezone.utc).hour

    if config.KILL_ZONE_PRE_LONDON_START <= h < config.KILL_ZONE_PRE_LONDON_END:
        return "PRE_LONDON"
    if config.KILL_ZONE_LONDON_START <= h < config.KILL_ZONE_LONDON_END:
        return "LONDON"
    if config.KILL_ZONE_PRE_NY_START <= h < config.KILL_ZONE_PRE_NY_END:
        return "PRE_NY"
    if config.KILL_ZONE_NY_START <= h < config.KILL_ZONE_NY_END:
        return "NEW_YORK"

    # Silver Bullet — independent window, session na ho tab bhi valid
    if _is_silver_bullet():
        return "SILVER_BULLET"

    return ""


def _is_silver_bullet() -> bool:
    h = datetime.now(timezone.utc).hour
    return any(s <= h < e for s, e in config.SILVER_BULLET_WINDOWS)


# ─────────────────────────────────────────────
#  V7.3: AMD — Accumulation, Manipulation, Distribution
# ─────────────────────────────────────────────

def _check_amd(df, trend) -> bool:
    """
    Power of 3 pattern:
    1. Accumulation — pehli candles tight range (consolidation)
    2. Manipulation — beech mein fake move opposite direction
       (liquidity grab, range se bahar wick)
    3. Distribution — last candles asal direction mein strong move

    Return True agar yeh pattern current trend ke sath match kare.
    """
    if df is None or len(df) < config.AMD_LOOKBACK + 2:
        return False

    closed = df.iloc[:-1].tail(config.AMD_LOOKBACK).reset_index(drop=True)
    n = len(closed)
    if n < 12:
        return False

    third = n // 3
    accumulation = closed.iloc[:third]
    manipulation = closed.iloc[third:2*third]
    distribution = closed.iloc[2*third:]

    # 1. Accumulation — range tight honi chahiye
    acc_range = accumulation["high"].max() - accumulation["low"].min()
    avg_range = (closed["high"] - closed["low"]).mean()
    if avg_range <= 0:
        return False
    is_tight = acc_range < avg_range * third * 0.8

    # 2. Manipulation — range se bahar wick (opposite direction fake move)
    acc_high, acc_low = accumulation["high"].max(), accumulation["low"].min()
    if trend == "BULLISH":
        # Manipulation phase mein neeche fake breakdown hona chahiye
        manip_break = manipulation["low"].min() < acc_low
    else:
        manip_break = manipulation["high"].max() > acc_high

    # 3. Distribution — asal direction mein strong move
    dist_start = distribution.iloc[0]["open"]
    dist_end   = distribution.iloc[-1]["close"]
    if trend == "BULLISH":
        is_distributing = dist_end > dist_start and \
                          dist_end > acc_high
    else:
        is_distributing = dist_end < dist_start and \
                          dist_end < acc_low

    amd_match = is_tight and manip_break and is_distributing

    if amd_match:
        log_event("INFO", f"GOLD: AMD pattern confirmed [{trend}]")

    return amd_match


def _bos_single(df):
    """Ek timeframe ka BOS-based trend (swing high/low compare)."""
    if df is None or len(df) < 30: return "NONE"
    closed = df.iloc[:-1].reset_index(drop=True)
    sh,sl=[],[]
    for i in range(2, min(len(closed)-2,30)):
        c,p,n = closed.iloc[i],closed.iloc[i-1],closed.iloc[i+1]
        if c["high"]>p["high"] and c["high"]>n["high"]: sh.append(c["high"])
        if c["low"]<p["low"] and c["low"]<n["low"]: sl.append(c["low"])
    if len(sh)<2 or len(sl)<2:
        r=closed.tail(20).reset_index(drop=True)
        si,hi=r["low"].idxmin(),r["high"].idxmax()
        if si<hi: return "BULLISH"
        if hi<si: return "BEARISH"
        return "NONE"
    hh,hl = sh[-1]>sh[-2], sl[-1]>sl[-2]
    lh,ll = sh[-1]<sh[-2], sl[-1]<sl[-2]
    if hh and hl: return "BULLISH"
    if lh and ll: return "BEARISH"
    if hh: return "BULLISH"
    if ll: return "BEARISH"
    return "NONE"


def _fast_recent_trend(df, candles: int = 6) -> str:
    """
    Sirf last N candles ka higher-highs/higher-lows (ya lower)
    check karo — swing-based se zyada FAST react karta hai,
    lagging problem nahi hoti.
    """
    if df is None or len(df) < candles + 2:
        return "NONE"
    closed = df.iloc[:-1].tail(candles).reset_index(drop=True)
    if len(closed) < 3:
        return "NONE"

    ups = downs = 0
    for i in range(1, len(closed)):
        if closed.iloc[i]["high"] > closed.iloc[i-1]["high"] and            closed.iloc[i]["low"]  > closed.iloc[i-1]["low"]:
            ups += 1
        elif closed.iloc[i]["high"] < closed.iloc[i-1]["high"] and              closed.iloc[i]["low"]  < closed.iloc[i-1]["low"]:
            downs += 1

    total = len(closed) - 1
    if total == 0:
        return "NONE"
    if ups / total >= 0.6:
        return "BULLISH"
    if downs / total >= 0.6:
        return "BEARISH"
    return "NONE"


def _momentum_override(df_m15) -> str:
    """
    IMPROVEMENT 2: Displacement/momentum-based override.
    Agar recent candles mein ek bahut bara directional move
    ho (ATR ka 3x+), yeh khud trend confirm karta hai — chahe
    swing-based BOS abhi lag kar raha ho.
    """
    if df_m15 is None or len(df_m15) < 20:
        return "NONE"
    closed = df_m15.iloc[:-1].reset_index(drop=True)
    atr = _calc_atr(df_m15, 14)
    if atr <= 0:
        return "NONE"

    recent = closed.tail(6)
    net_move = recent.iloc[-1]["close"] - recent.iloc[0]["open"]

    if net_move > atr * 2.5:
        log_event("INFO",
            f"GOLD: MOMENTUM OVERRIDE — bara bullish move "
            f"(${net_move:.2f} vs ATR ${atr:.2f})"
        )
        return "BULLISH"
    if net_move < -atr * 2.5:
        log_event("INFO",
            f"GOLD: MOMENTUM OVERRIDE — bara bearish move "
            f"(${abs(net_move):.2f} vs ATR ${atr:.2f})"
        )
        return "BEARISH"
    return "NONE"


def _get_trend_bos(df_h1, df_m30, df_m15=None) -> str:
    """
    IMPROVEMENT 1: Majority Vote — H1 ab "hamesha jeetega" nahi,
    balki H1+M30+M15 teeno ek-ek vote dete hain. 2/3 agree = trend.

    IMPROVEMENT 2: Momentum Override — agar M15 pe ek bahut bara
    displacement move ho (recent structure abhi update na hui ho
    tab bhi), yeh directly trend confirm kar deta hai.
    """
    h1t  = _bos_single(df_h1)
    m30t = _bos_single(df_m30)
    m15t = _bos_single(df_m15) if df_m15 is not None else "NONE"

    log_event("INFO", f"GOLD: H1_BOS={h1t} M30_BOS={m30t} M15_BOS={m15t}")

    # ── Momentum override sabse pehle check karo — sabse fast signal ──
    momentum = _momentum_override(df_m15)
    if momentum != "NONE":
        return momentum

    # ── Fast recent-candle trend bhi ek "vote" ki tarah use karo ──
    fast_m15 = _fast_recent_trend(df_m15, 6) if df_m15 is not None else "NONE"

    votes = [v for v in (h1t, m30t, m15t, fast_m15) if v != "NONE"]
    if not votes:
        return "NONE"

    bull_count = votes.count("BULLISH")
    bear_count = votes.count("BEARISH")

    log_event("INFO",
        f"GOLD: Votes — BULLISH:{bull_count} BEARISH:{bear_count} "
        f"(fast_m15={fast_m15})"
    )

    if bull_count >= 2 and bull_count > bear_count:
        return "BULLISH"
    if bear_count >= 2 and bear_count > bull_count:
        return "BEARISH"

    # Majority na bane to purana fallback — H1 priority
    if h1t != "NONE":
        return h1t
    return "NONE"


def _check_d1_levels(df_d1, trend, current) -> bool:
    if df_d1 is None or len(df_d1) < 5: return True
    closed = df_d1.iloc[:-1].reset_index(drop=True)
    recent = closed.tail(10)
    sh,sl=[],[]
    for i in range(1,len(recent)-1):
        c,p,n = recent.iloc[i],recent.iloc[i-1],recent.iloc[i+1]
        if c["high"]>p["high"] and c["high"]>n["high"]: sh.append(c["high"])
        if c["low"]<p["low"] and c["low"]<n["low"]: sl.append(c["low"])
    buf = 20.0
    if trend=="BULLISH" and sh:
        nr = min(sh, key=lambda x: abs(x-current))
        if current >= nr-buf:
            log_event("INFO", f"GOLD: near D1 resistance {nr:.2f} — Skip.")
            return False
    if trend=="BEARISH" and sl:
        ns = min(sl, key=lambda x: abs(x-current))
        if current <= ns+buf:
            log_event("INFO", f"GOLD: near D1 support {ns:.2f} — Skip.")
            return False
    return True


def _check_adx(df) -> bool:
    if df is None or len(df) < 16: return True
    r = df.tail(15).reset_index(drop=True)
    pdm,mdm,trs=[],[],[]
    for i in range(1,len(r)):
        h,l = r.iloc[i]["high"], r.iloc[i]["low"]
        ph,pl,pc = r.iloc[i-1]["high"],r.iloc[i-1]["low"],r.iloc[i-1]["close"]
        up,dn = h-ph, pl-l
        pdm.append(up if up>dn and up>0 else 0)
        mdm.append(dn if dn>up and dn>0 else 0)
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    ts=sum(trs)
    if ts==0: return True
    pdi,mdi = sum(pdm)/ts*100, sum(mdm)/ts*100
    adx = abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0
    log_event("INFO", f"GOLD: ADX={adx:.1f}")
    return adx >= 20.0


def _find_m15_zone(df_m15, trend) -> dict:
    if df_m15 is None or len(df_m15)<10: return None
    current = df_m15.iloc[-2]["close"]
    obs = ind.get_order_blocks(df_m15, trend)
    if obs:
        # V8.2: OB Freshness check — sirf pehli 3 candidate OBs try karo,
        # jo bahut retest ho chuki hain unko skip karo (stale)
        for ob in obs[:3]:
            if not ind.price_in_zone(current, ob["top"], ob["bottom"], BUF*3):
                continue
            ob_idx = ob.get("idx", 0)
            if not _is_ob_fresh(df_m15, ob["top"], ob["bottom"], ob_idx):
                log_event("INFO", "GOLD: OB stale (bahut retest ho chuka) — skip.")
                continue
            return {"type":"OB_M15","top":ob["top"],"bottom":ob["bottom"]}
    fvgs = ind.get_fvg(df_m15, trend)
    if fvgs:
        f=fvgs[0]
        if ind.price_in_zone(current, f["top"], f["bottom"], BUF*2):
            return {"type":"FVG_M15","top":f["top"],"bottom":f["bottom"]}
    liq = ind.get_liquidity_levels(df_m15, lookback=20)
    c = df_m15.iloc[-2]
    if trend=="BULLISH" and liq["sell_side"]:
        rl = min(liq["sell_side"][-3:]) if len(liq["sell_side"])>=3 else liq["sell_side"][-1]
        if c["low"]<rl and c["close"]>rl:
            return {"type":"LIQ_M15","top":rl+BUF,"bottom":rl-BUF}
    elif trend=="BEARISH" and liq["buy_side"]:
        rh = max(liq["buy_side"][-3:]) if len(liq["buy_side"])>=3 else liq["buy_side"][-1]
        if c["high"]>rh and c["close"]<rh:
            return {"type":"LIQ_M15","top":rh+BUF,"bottom":rh-BUF}
    return None


def _is_ote_entry(current, zone, trend) -> bool:
    if not zone: return False
    top, bottom = zone["top"], zone["bottom"]
    mid = (top+bottom)/2
    if trend == "BULLISH":
        return current <= mid + (top-bottom)*0.15
    else:
        return current >= mid - (top-bottom)*0.15


def _m5_confirm(df_m5, trend) -> bool:
    if df_m5 is None or len(df_m5)<5: return False
    current = df_m5.iloc[-2]["close"]
    obs = ind.get_order_blocks(df_m5, trend)
    if obs and ind.price_in_zone(current, obs[0]["top"], obs[0]["bottom"], BUF*2):
        return True
    fvgs = ind.get_fvg(df_m5, trend)
    if fvgs and ind.price_in_zone(current, fvgs[0]["top"], fvgs[0]["bottom"], BUF):
        return True
    liq = ind.get_liquidity_levels(df_m5, lookback=15)
    c = df_m5.iloc[-2]
    if trend=="BULLISH" and liq["sell_side"]:
        rl = min(liq["sell_side"][-3:]) if len(liq["sell_side"])>=3 else liq["sell_side"][-1]
        if c["low"]<rl and c["close"]>rl: return True
    elif trend=="BEARISH" and liq["buy_side"]:
        rh = max(liq["buy_side"][-3:]) if len(liq["buy_side"])>=3 else liq["buy_side"][-1]
        if c["high"]>rh and c["close"]<rh: return True
    return False


def _m1_entry(df_m1, trend) -> bool:
    if df_m1 is None or len(df_m1)<5: return True
    c = df_m1.iloc[-2]
    fvgs = ind.get_fvg(df_m1, trend)
    if fvgs:
        f=fvgs[0]
        if trend=="BULLISH" and c["close"]>=f["bottom"]: return True
        if trend=="BEARISH" and c["close"]<=f["top"]: return True
    if trend=="BULLISH" and c["close"]>c["open"]: return True
    if trend=="BEARISH" and c["close"]<c["open"]: return True
    body = abs(c["close"]-c["open"])
    if trend=="BULLISH" and (min(c["open"],c["close"])-c["low"])>body*1.5: return True
    if trend=="BEARISH" and (c["high"]-max(c["open"],c["close"]))>body*1.5: return True
    return False


def _m1_entry_confirmed(df_m1, trend) -> bool:
    if df_m1 is None or len(df_m1) < 6:
        return _m1_entry(df_m1, trend)
    c1, c2 = df_m1.iloc[-2], df_m1.iloc[-3]
    if trend == "BULLISH":
        two_ok = c1["close"]>c1["open"] and c2["close"]>c2["open"]
    else:
        two_ok = c1["close"]<c1["open"] and c2["close"]<c2["open"]
    if not two_ok:
        log_event("INFO", "GOLD: M1 2-candle confirm fail.")
        return False
    return _m1_entry(df_m1, trend)


def _calc_rsi(df, period=14) -> float:
    if df is None or len(df) < period+2: return 50.0
    closes = df["close"].tail(period+1).reset_index(drop=True)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff,0)); losses.append(max(-diff,0))
    avg_gain, avg_loss = sum(gains)/period, sum(losses)/period
    if avg_loss == 0: return 100.0
    rs = avg_gain/avg_loss
    return 100 - (100/(1+rs))


def _log_momentum_info(df_h1, trend):
    """RSI ab sirf informational — koi trade block nahi karta."""
    rsi = _calc_rsi(df_h1, config.RSI_PERIOD)
    log_event("INFO", f"GOLD: H1 RSI={rsi:.1f} (info only, no block)")


_break_retest_state = {}

def check_break_retest(df_m15, trend, zone) -> bool:
    global _break_retest_state
    if df_m15 is None or len(df_m15) < 3 or not zone:
        return False
    state = _break_retest_state
    if not state or state.get("trend") != trend:
        _break_retest_state = {"trend":trend,"top":zone["top"],
                               "bottom":zone["bottom"],"bars_waited":0}
        log_event("INFO", "GOLD: Break-Retest wait shuru.")
        return False
    state["bars_waited"] += 1
    if state["bars_waited"] > config.BREAK_RETEST_WINDOW:
        log_event("INFO", "GOLD: Retest window expire.")
        _break_retest_state = {}
        return False
    c = df_m15.iloc[-2]
    top, bottom = state["top"], state["bottom"]
    if trend == "BULLISH":
        touched = c["low"]<=top and c["close"]>bottom
        wick = (min(c["open"],c["close"])-c["low"]) > abs(c["close"]-c["open"])*0.8
        if touched and (wick or c["close"]>c["open"]):
            log_event("INFO", "GOLD: Retest confirmed!")
            _break_retest_state = {}
            return True
    elif trend == "BEARISH":
        touched = c["high"]>=bottom and c["close"]<top
        wick = (c["high"]-max(c["open"],c["close"])) > abs(c["close"]-c["open"])*0.8
        if touched and (wick or c["close"]<c["open"]):
            log_event("INFO", "GOLD: Retest confirmed!")
            _break_retest_state = {}
            return True
    return False


def _calc_atr(df, period=ATR_PERIOD) -> float:
    if df is None or len(df)<period+2: return 0.0
    r = df.tail(period+1).reset_index(drop=True)
    trs=[]
    for i in range(1,len(r)):
        h,l,pc = r.iloc[i]["high"],r.iloc[i]["low"],r.iloc[i-1]["close"]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0.0


def _calc_sl_atr(df_m15, trend, entry) -> dict:
    atr = _calc_atr(df_m15, ATR_PERIOD)
    sl_size = max(MIN_SL, min(atr*config.ATR_MULTIPLIER_GOLD if atr>0 else MIN_SL, MAX_SL))
    sl = round(entry-sl_size if trend=="BULLISH" else entry+sl_size, 3)
    return {"sl":sl,"size":sl_size,"atr":atr}


# ─────────────────────────────────────────────
#  IMPROVEMENT 1: WEEKLY QUOTA FALLBACK
#  Agar hafte ke Wed/Thu tak minimum trades na hui hon,
#  score threshold temporarily kam kar do
# ─────────────────────────────────────────────

import json, os

WEEKLY_FILE = "data/gold_weekly_signals.json"

def _get_week_key() -> str:
    now = datetime.now(timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week}"

def _load_weekly():
    try:
        if os.path.exists(WEEKLY_FILE):
            with open(WEEKLY_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_weekly(data):
    try:
        os.makedirs("data", exist_ok=True)
        with open(WEEKLY_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log_event("WARNING", f"Weekly file save fail: {e}")

def _record_weekly_signal():
    data = _load_weekly()
    key = _get_week_key()
    data[key] = data.get(key, 0) + 1
    _save_weekly(data)

def _get_quota_adjustment() -> int:
    """
    Wednesday tak (weekday>=2) agar 0 trades hon → -1 threshold
    Thursday tak (weekday>=3) agar <2 trades hon → -1 threshold
    Friday tak (weekday>=4) agar <3 trades hon → -2 threshold
    """
    data  = _load_weekly()
    key   = _get_week_key()
    count = data.get(key, 0)
    now   = datetime.now(timezone.utc)
    wday  = now.weekday()   # 0=Mon .. 6=Sun

    if wday >= 4 and count < 3:
        log_event("INFO", f"GOLD: Weekly quota low ({count}) — threshold -2")
        return -2
    if wday >= 3 and count < 2:
        log_event("INFO", f"GOLD: Weekly quota low ({count}) — threshold -1")
        return -1
    if wday >= 2 and count < 1:
        log_event("INFO", f"GOLD: Weekly quota low ({count}) — threshold -1")
        return -1
    return 0


# ─────────────────────────────────────────────
#  IMPROVEMENT 2: VOLUME CONFIRMATION
# ─────────────────────────────────────────────

def _check_volume(df_m15) -> bool:
    """Entry candle ka volume average se zyada hona chahiye."""
    if df_m15 is None or len(df_m15) < 20 or "tick_volume" not in df_m15.columns:
        return True   # Data nahi to neutral allow
    closed = df_m15.iloc[:-1]
    avg_vol = closed["tick_volume"].tail(20).mean()
    entry_vol = closed["tick_volume"].iloc[-1]
    return entry_vol >= avg_vol * 0.9   # Thoda loose — 90% bhi chalega


# ─────────────────────────────────────────────
#  IMPROVEMENT 3: DAILY PIVOT POINTS (Classic Floor Pivots)
# ─────────────────────────────────────────────

def _calc_pivots(df_d1) -> dict:
    """PP, R1, S1 — kal ke H/L/C se classic floor pivot formula."""
    if df_d1 is None or len(df_d1) < 2:
        return {}
    closed = df_d1.iloc[:-1]
    prev = closed.iloc[-1]
    H, L, C = prev["high"], prev["low"], prev["close"]
    PP = (H + L + C) / 3
    R1 = 2*PP - L
    S1 = 2*PP - H
    return {"PP": PP, "R1": R1, "S1": S1}

def _check_pivot_bonus(current, trend, pivots) -> bool:
    """Price kisi pivot level ke paas ho to bonus (institutional level)."""
    if not pivots:
        return False
    tolerance = 3.0   # $3 tolerance
    for level_name, level_val in pivots.items():
        if abs(current - level_val) <= tolerance:
            log_event("INFO", f"GOLD: Price near pivot {level_name}={level_val:.2f}")
            return True
    return False


# ─────────────────────────────────────────────
#  IMPROVEMENT 4: STRUCTURE-BASED TP (Draw on Liquidity)
# ─────────────────────────────────────────────

def _find_liquidity_target(df_h1, entry, trend, sl_size, rr_default=3.0):
    """
    Agar koi qareeb swing high/low (liquidity pool) 1:3 se pehle
    mile, wahi target banao — RR minimum 1.5 zaroor rahe.
    """
    default_tp = entry + sl_size*rr_default if trend=="BULLISH" else entry - sl_size*rr_default

    if df_h1 is None or len(df_h1) < 20:
        return default_tp

    recent = df_h1.tail(20)
    if trend == "BULLISH":
        candidates = [h for h in recent["high"] if h > entry + sl_size*1.5 and h < default_tp]
        if candidates:
            target = min(candidates)   # Nearest liquidity pool
            log_event("INFO", f"GOLD: Liquidity target found at {target:.2f} (instead of {default_tp:.2f})")
            return target
    else:
        candidates = [l for l in recent["low"] if l < entry - sl_size*1.5 and l > default_tp]
        if candidates:
            target = max(candidates)
            log_event("INFO", f"GOLD: Liquidity target found at {target:.2f} (instead of {default_tp:.2f})")
            return target

    return default_tp


# ─────────────────────────────────────────────
#  IMPROVEMENT 5: ATR PERCENTILE (Volatility Regime)
# ─────────────────────────────────────────────

def _check_atr_regime(df_m15) -> bool:
    """
    Agar current ATR apne 20-period average se 2x zyada ho
    (abnormal spike/news chaos) — caution flag True return karo.
    """
    if df_m15 is None or len(df_m15) < 25:
        return False
    current_atr = _calc_atr(df_m15, 14)
    # Rolling ATR average — simplified: last 20 candles ki range avg
    closed = df_m15.iloc[:-1].tail(20)
    avg_range = (closed["high"] - closed["low"]).mean()
    if avg_range <= 0:
        return False
    is_abnormal = current_atr > avg_range * 2.5
    if is_abnormal:
        log_event("INFO", f"GOLD: ATR abnormal spike detected (ATR={current_atr:.2f} vs avg={avg_range:.2f})")
    return is_abnormal


# ════════════════════════════════════════════════════════════
#  V8.2 — INSTITUTIONAL FOOTPRINT DETECTION
#  "Retail SL hit hone ke baad hi entry — sirf zone touch pe nahi"
# ════════════════════════════════════════════════════════════

INST_TOLERANCE_PCT   = 0.0008   # EQH/EQL cluster tolerance
INST_PIERCE_BUFFER   = 1.5      # $ — kam se kam itna aage nikalna chahiye
DISPLACEMENT_MULT    = 1.8      # Body kam se kam itni bari (avg se)
MAX_OB_RETESTS       = 2        # Isse zyada retest ho to OB "stale"

# ─────────────────────────────────────────────
#  1. EQUAL HIGHS/LOWS — Retail Stop Clusters
# ─────────────────────────────────────────────

def _find_equal_levels(df, lookback: int = 25) -> dict:
    """
    Jahan 2+ highs (ya lows) ek dusre ke bahut paas hon —
    yeh retail stop-loss cluster hai (obvious S/R levels
    jahan sab log SL rakhte hain).
    """
    if df is None or len(df) < lookback + 2:
        return {"eqh": [], "eql": []}

    closed = df.iloc[:-1].tail(lookback).reset_index(drop=True)
    highs  = closed["high"].tolist()
    lows   = closed["low"].tolist()

    eqh, eql = [], []

    for i in range(len(highs)):
        for j in range(i+1, len(highs)):
            if abs(highs[i] - highs[j]) / highs[i] <= INST_TOLERANCE_PCT:
                level = (highs[i] + highs[j]) / 2
                if not any(abs(level - e) < 1.0 for e in eqh):
                    eqh.append(level)

    for i in range(len(lows)):
        for j in range(i+1, len(lows)):
            if abs(lows[i] - lows[j]) / lows[i] <= INST_TOLERANCE_PCT:
                level = (lows[i] + lows[j]) / 2
                if not any(abs(level - e) < 1.0 for e in eql):
                    eql.append(level)

    return {"eqh": eqh, "eql": eql}


# ─────────────────────────────────────────────
#  2. DISPLACEMENT CANDLE — Asal Institutional Footprint
# ─────────────────────────────────────────────

def _is_displacement_candle(candle, avg_body: float, direction: str) -> bool:
    """
    Strong conviction candle — body bara, wick chota, FVG
    banane wali. Yeh institutions ke enter hone ka signal hai.
    """
    body = abs(candle["close"] - candle["open"])
    if body < avg_body * DISPLACEMENT_MULT:
        return False

    total_range = candle["high"] - candle["low"]
    if total_range <= 0:
        return False

    if direction == "BULLISH":
        if candle["close"] <= candle["open"]:
            return False
        upper_wick = candle["high"] - candle["close"]
        wick_ratio = upper_wick / total_range
    else:
        if candle["close"] >= candle["open"]:
            return False
        lower_wick = candle["close"] - candle["low"]
        wick_ratio = lower_wick / total_range

    return wick_ratio < 0.35   # Opposite wick chota hona chahiye = conviction


# ─────────────────────────────────────────────
#  3. VOLUME SPIKE ON SWEEP CANDLE
# ─────────────────────────────────────────────

def _has_volume_spike(df, idx: int, avg_vol: float) -> bool:
    if "tick_volume" not in df.columns or avg_vol <= 0:
        return True   # Data nahi to neutral allow
    try:
        vol = df.iloc[idx]["tick_volume"]
        return vol >= avg_vol * 1.3
    except Exception:
        return True


# ─────────────────────────────────────────────
#  4. JUDAS SWING — Session Open Fake-Out
# ─────────────────────────────────────────────

def _is_judas_swing_window() -> bool:
    """Session open ke pehle 30 minute — fake move ka window."""
    now = datetime.now(timezone.utc)
    for start_h in (7, 12):   # London open, NY open
        if now.hour == start_h and now.minute <= 30:
            return True
    return False


# ─────────────────────────────────────────────
#  5. OB FRESHNESS — Pehli Baar Use Na Hui Ho
# ─────────────────────────────────────────────

def _is_ob_fresh(df_m15, ob_top: float, ob_bottom: float, ob_idx: int) -> bool:
    """
    OB banne ke baad se ab tak kitni baar price wapas
    is zone mein aayi hai — zyada baar aaya to "stale" hai
    (retail ne discover kar liya, institutional edge kam ho gaya).
    """
    if df_m15 is None or len(df_m15) < ob_idx + 5:
        return True

    closed = df_m15.iloc[:-1].reset_index(drop=True)
    after  = closed.iloc[ob_idx+1:]
    if after.empty:
        return True

    touches = 0
    was_inside = False
    for _, c in after.iterrows():
        inside = c["low"] <= ob_top and c["high"] >= ob_bottom
        if inside and not was_inside:
            touches += 1
        was_inside = inside

    return touches <= MAX_OB_RETESTS


# ─────────────────────────────────────────────
#  6. MAIN: INSTITUTIONAL FOOTPRINT ZONE FINDER
#  H1 (external) priority, M15 (internal) fallback
# ─────────────────────────────────────────────

def _find_institutional_zone(df_h1, df_m15, trend, point) -> dict:
    """
    Poora institutional footprint check:
    1. EQH/EQL dhundo (H1 external priority, M15 internal fallback)
    2. Price un se PAR (beyond) nikli ho — sirf touch nahi
    3. Us sweep ke baad Displacement candle bane
    4. Volume spike ho sweep candle pe
    5. (Bonus) Judas Swing window mein ho to extra confidence

    Return: zone dict with type="INST_SWEEP" ya None
    """
    for df_check, label, lookback in [(df_h1,"H1",30), (df_m15,"M15",20)]:
        if df_check is None or len(df_check) < lookback + 5:
            continue

        levels = _find_equal_levels(df_check, lookback)
        closed = df_check.iloc[:-1].reset_index(drop=True)
        if len(closed) < 3:
            continue

        c        = closed.iloc[-1]
        prev_avg_body = abs(closed["close"] - closed["open"]).tail(20).mean()
        avg_vol  = closed["tick_volume"].tail(20).mean() if "tick_volume" in closed.columns else 0

        if trend == "BULLISH" and levels["eql"]:
            # Nearest EQL jo price ne pierce ki ho
            for level in sorted(levels["eql"], key=lambda x: abs(x - c["close"])):
                pierced = c["low"] < level - INST_PIERCE_BUFFER and c["close"] > level
                if not pierced:
                    continue
                if not _is_displacement_candle(c, prev_avg_body, "BULLISH"):
                    continue
                if not _has_volume_spike(closed, len(closed)-1, avg_vol):
                    continue

                log_event("INFO",
                    f"GOLD: INSTITUTIONAL sweep [{label}] — EQL={level:.2f} "
                    f"pierced, displacement confirmed!"
                )
                return {
                    "type":   f"INST_SWEEP_{label}",
                    "top":    level + INST_PIERCE_BUFFER,
                    "bottom": c["low"] - 1.0
                }

        elif trend == "BEARISH" and levels["eqh"]:
            for level in sorted(levels["eqh"], key=lambda x: abs(x - c["close"])):
                pierced = c["high"] > level + INST_PIERCE_BUFFER and c["close"] < level
                if not pierced:
                    continue
                if not _is_displacement_candle(c, prev_avg_body, "BEARISH"):
                    continue
                if not _has_volume_spike(closed, len(closed)-1, avg_vol):
                    continue

                log_event("INFO",
                    f"GOLD: INSTITUTIONAL sweep [{label}] — EQH={level:.2f} "
                    f"pierced, displacement confirmed!"
                )
                return {
                    "type":   f"INST_SWEEP_{label}",
                    "top":    c["high"] + 1.0,
                    "bottom": level - INST_PIERCE_BUFFER
                }

    return None


def _calc_score(trend, m15_trend, zone, m5c, m1t, news_dir, session, amd_ok,
                volume_ok=True, pivot_ok=False, atr_abnormal=False,
                is_institutional=False, judas_ok=False) -> int:
    s=0
    if trend!="NONE": s+=1
    if m15_trend==trend: s+=1
    if zone:
        zt=zone.get("type","")
        if "INST_SWEEP" in zt: s+=6   # V8.2 — sabse strong signal
        elif "OB" in zt: s+=2
        elif "FVG" in zt: s+=1
        elif "LIQ" in zt: s+=1
    if m5c: s+=1
    if m1t: s+=1
    if news_dir: s+=1
    if session in ("LONDON","NEW_YORK"): s+=1
    if session in ("PRE_LONDON","PRE_NY"): s+=1
    if session == "SILVER_BULLET": s+=2
    if amd_ok: s+=2
    # V8.1 improvements
    if volume_ok: s+=1          # Real institutional volume
    if pivot_ok:  s+=1          # Price kisi pivot level ke paas
    if atr_abnormal: s-=2       # Abnormal volatility — caution penalty
    # V8.2 improvements
    if judas_ok: s+=2           # Session open Judas Swing window
    return s


def _is_weekend() -> bool:
    now=datetime.now(timezone.utc); w=now.weekday()
    if w==4 and now.hour>=21: return True
    if w in (5,6): return True
    return False

def _is_friday_cutoff() -> bool:
    now=datetime.now(timezone.utc)
    return now.weekday()==4 and now.hour>=20

def should_close_for_weekend() -> bool:
    now=datetime.now(timezone.utc)
    return now.weekday()==4 and now.hour>=20 and now.minute>=30
