# ============================================================
#  strategy_ict.py — ICT Strategy V7.3
#  NEW: Pre-London/Pre-NY sessions, Silver Bullet standalone
#       window, AMD (Accumulation-Manipulation-Distribution)
# ============================================================

from datetime import datetime, timezone
import config
import indicators as ind
from logger import log_event

MIN_SCORE = 7
ATR_PERIOD = 14
PDH_PDL_BUFFER = 10


def is_kill_zone() -> dict:
    """
    Session windows: Pre-London, London, Pre-NY, NY, Asia.
    Silver Bullet standalone window bhi valid hai — chahe
    baaki sessions active na ho.
    """
    h = datetime.now(timezone.utc).hour

    if config.KILL_ZONE_PRE_LONDON_START <= h < config.KILL_ZONE_PRE_LONDON_END:
        return {"active":True,"name":"PRE_LONDON"}
    if config.KILL_ZONE_LONDON_START <= h < config.KILL_ZONE_LONDON_END:
        return {"active":True,"name":"LONDON"}
    if config.KILL_ZONE_PRE_NY_START <= h < config.KILL_ZONE_PRE_NY_END:
        return {"active":True,"name":"PRE_NY"}
    if config.KILL_ZONE_NY_START <= h < config.KILL_ZONE_NY_END:
        return {"active":True,"name":"NEW_YORK"}
    if h >= config.KILL_ZONE_ASIA_START or h < config.KILL_ZONE_ASIA_END:
        return {"active":True,"name":"ASIA"}

    # Silver Bullet — apne aap mein valid window
    if is_silver_bullet():
        return {"active":True,"name":"SILVER_BULLET"}

    return {"active":False,"name":""}


def is_silver_bullet() -> bool:
    h = datetime.now(timezone.utc).hour
    return any(s<=h<e for s,e in config.SILVER_BULLET_WINDOWS)

def _is_friday_cutoff() -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday()==4 and now.hour>=20

def _is_good_session_pair(symbol, session) -> bool:
    return symbol in config.SESSION_PAIRS.get(session, [])


# ─────────────────────────────────────────────
#  V7.3: AMD — Power of 3
# ─────────────────────────────────────────────

def _check_amd(df, trend) -> bool:
    """Accumulation (tight range) -> Manipulation (fake break)
    -> Distribution (real move) — trend ke saath match."""
    if df is None or len(df) < config.AMD_LOOKBACK + 2:
        return False
    closed = df.iloc[:-1].tail(config.AMD_LOOKBACK).reset_index(drop=True)
    n = len(closed)
    if n < 12: return False
    third = n // 3
    acc  = closed.iloc[:third]
    manp = closed.iloc[third:2*third]
    dist = closed.iloc[2*third:]

    acc_range = acc["high"].max() - acc["low"].min()
    avg_range = (closed["high"] - closed["low"]).mean()
    if avg_range <= 0: return False
    is_tight = acc_range < avg_range * third * 0.8

    acc_high, acc_low = acc["high"].max(), acc["low"].min()
    if trend == "BULLISH":
        manip_break = manp["low"].min() < acc_low
    else:
        manip_break = manp["high"].max() > acc_high

    dist_start, dist_end = dist.iloc[0]["open"], dist.iloc[-1]["close"]
    if trend == "BULLISH":
        is_dist = dist_end > dist_start and dist_end > acc_high
    else:
        is_dist = dist_end < dist_start and dist_end < acc_low

    result = is_tight and manip_break and is_dist
    if result:
        log_event("INFO", f"ICT: AMD pattern confirmed [{trend}]")
    return result


def _get_trend_bos(df_m15, df_m5, df_h1=None) -> str:
    def bos(df, lookback=20):
        if df is None or len(df) < lookback+2: return "NONE"
        closed = df.iloc[:-1].reset_index(drop=True)
        sh,sl=[],[]
        for i in range(2, min(len(closed)-2, lookback)):
            c,p,n = closed.iloc[i],closed.iloc[i-1],closed.iloc[i+1]
            if c["high"]>p["high"] and c["high"]>n["high"]: sh.append(c["high"])
            if c["low"]<p["low"] and c["low"]<n["low"]: sl.append(c["low"])
        if len(sh)<2 or len(sl)<2:
            r=closed.tail(15).reset_index(drop=True)
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

    m15t = bos(df_m15, 20)
    if df_m5 is not None and len(df_m5)>=10:
        m5t = bos(df_m5, 10)
        if m5t!="NONE" and m5t!=m15t:
            log_event("INFO", f"M15={m15t} M5={m5t} conflict.")
            return "NONE"
    if df_h1 is not None:
        h1t = bos(df_h1, 20)
        if h1t!="NONE" and h1t!=m15t:
            log_event("INFO", f"H1={h1t} M15={m15t} conflict.")
            return "NONE"
    return m15t


def _find_quality_zone(df_m15, df_m5, trend, point) -> dict:
    buf = config.SL_BUFFER_POINTS_FOREX * point * 10
    current = df_m5.iloc[-2]["close"] if df_m5 is not None and len(df_m5)>2 \
              else df_m15.iloc[-2]["close"]
    if df_m15 is None or len(df_m15)<10: return None
    closed = df_m15.iloc[:-1].reset_index(drop=True)
    avg_body = (abs(closed["close"]-closed["open"])).tail(20).mean()

    obs = ind.get_order_blocks(df_m15, trend)
    for ob in obs[:5]:
        ob_top, ob_bottom = ob["top"], ob["bottom"]
        ob_idx = ob.get("idx", 0)
        if ob_idx < len(closed):
            ob_c = closed.iloc[ob_idx]
            if abs(ob_c["close"]-ob_c["open"]) < avg_body*0.5:
                continue
        if ob_idx+3 < len(closed):
            move = abs(closed.iloc[ob_idx+3]["close"]-closed.iloc[ob_idx]["close"])
            avg_range = (closed["high"]-closed["low"]).tail(20).mean()
            if move < avg_range:
                continue
        if not ind.price_in_zone(current, ob_top, ob_bottom, buf*3):
            continue
        zone_type = "OB_Q"
        if df_m5 is not None:
            fvgs = ind.get_fvg(df_m5, trend)
            if fvgs and ind.price_in_zone(fvgs[0]["mid"], ob_top, ob_bottom, buf):
                zone_type = "OB_FVG_Q"
        return {"type":zone_type,"top":ob_top,"bottom":ob_bottom}

    breakers = _get_breakers(df_m15, trend)
    if breakers:
        br = breakers[0]
        if ind.price_in_zone(current, br["top"], br["bottom"], buf*3):
            return {"type":"BREAKER","top":br["top"],"bottom":br["bottom"]}
    return None


def _get_breakers(df, trend) -> list:
    if df is None or len(df)<5: return []
    closed = df.iloc[:-1].reset_index(drop=True)
    res=[]
    for i in range(2, min(len(closed)-1,30)):
        p,c = closed.iloc[i-1],closed.iloc[i]
        if trend=="BULLISH" and p["close"]<p["open"] and c["close"]>p["high"]:
            res.append({"top":p["high"],"bottom":p["low"]})
        elif trend=="BEARISH" and p["close"]>p["open"] and c["close"]<p["low"]:
            res.append({"top":p["high"],"bottom":p["low"]})
    res.reverse()
    return res


def _check_adx(df_m15) -> bool:
    if df_m15 is None or len(df_m15)<16: return True
    r = df_m15.tail(15).reset_index(drop=True)
    pdm,mdm,trs=[],[],[]
    for i in range(1,len(r)):
        h,l = r.iloc[i]["high"],r.iloc[i]["low"]
        ph,pl,pc = r.iloc[i-1]["high"],r.iloc[i-1]["low"],r.iloc[i-1]["close"]
        up,dn = h-ph, pl-l
        pdm.append(up if up>dn and up>0 else 0)
        mdm.append(dn if dn>up and dn>0 else 0)
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    ts=sum(trs)
    if ts==0: return True
    pdi,mdi=sum(pdm)/ts*100, sum(mdm)/ts*100
    adx = abs(pdi-mdi)/(pdi+mdi)*100 if (pdi+mdi)>0 else 0
    log_event("INFO", f"ICT ADX={adx:.1f}")
    return adx >= 18.0


def _check_pdh_pdl(df_m15, trend, current, point) -> bool:
    if df_m15 is None or len(df_m15)<50: return True
    buffer = PDH_PDL_BUFFER * point * 10
    closed = df_m15.iloc[:-1].copy()
    closed["date"] = closed["time"].dt.date
    today = closed["date"].iloc[-1]
    prev = closed[closed["date"]<today]
    if prev.empty: return True
    prev_day = prev[prev["date"]==prev["date"].iloc[-1]]
    pdh, pdl = prev_day["high"].max(), prev_day["low"].min()
    if trend=="BULLISH" and current >= pdh-buffer:
        log_event("INFO", f"ICT: near PDH {pdh:.5f} — Skip."); return False
    if trend=="BEARISH" and current <= pdl+buffer:
        log_event("INFO", f"ICT: near PDL {pdl:.5f} — Skip."); return False
    return True


def _calc_rsi(df, period=14) -> float:
    if df is None or len(df) < period+2: return 50.0
    closes = df["close"].tail(period+1).reset_index(drop=True)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i]-closes[i-1]
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag, al = sum(gains)/period, sum(losses)/period
    if al == 0: return 100.0
    rs = ag/al
    return 100 - (100/(1+rs))


def _check_momentum(df_h1, trend) -> bool:
    if df_h1 is None: return True
    rsi = _calc_rsi(df_h1, config.RSI_PERIOD)
    log_event("INFO", f"ICT: H1 RSI={rsi:.1f}")
    if trend=="BULLISH" and rsi >= config.RSI_OVERBOUGHT:
        log_event("INFO", "ICT: RSI overbought — Skip."); return False
    if trend=="BEARISH" and rsi <= config.RSI_OVERSOLD:
        log_event("INFO", "ICT: RSI oversold — Skip."); return False
    return True


def _is_ote_entry(current, zone, trend) -> bool:
    if not zone: return False
    top, bottom = zone["top"], zone["bottom"]
    mid = (top+bottom)/2
    if trend=="BULLISH":
        return current <= mid + (top-bottom)*0.15
    else:
        return current >= mid - (top-bottom)*0.15


def _calc_atr(df, period=ATR_PERIOD) -> float:
    if df is None or len(df)<period+2: return 0.0
    r = df.tail(period+1).reset_index(drop=True)
    trs=[]
    for i in range(1,len(r)):
        h,l,pc = r.iloc[i]["high"],r.iloc[i]["low"],r.iloc[i-1]["close"]
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    return sum(trs)/len(trs) if trs else 0.0


def _calc_sl_atr(df_m15, trend, entry, point) -> dict:
    atr = _calc_atr(df_m15)
    min_dist = config.MIN_SL_PIPS_FOREX * point * 10
    max_dist = 25 * point * 10
    sl_size = max(min_dist, min(atr*config.ATR_MULTIPLIER_FOREX if atr>0 else min_dist, max_dist))
    sl = round(entry-sl_size if trend=="BULLISH" else entry+sl_size, 5)
    return {"sl":sl,"size":sl_size,"atr":atr}


def _calc_score(h1_bos, m15_trend, zone, m1_type, session, symbol, sb, adx_ok, amd_ok) -> int:
    score=0
    if h1_bos==m15_trend and h1_bos!="NONE": score+=2
    elif h1_bos=="NONE": score+=1
    if zone:
        zt=zone.get("type","")
        if "OB_FVG" in zt: score+=3
        elif "OB_Q" in zt: score+=2
        elif "OB" in zt: score+=1
        if "BREAK" in zt: score+=1
    if m1_type=="FVG": score+=2
    elif m1_type in ("LIQ","CANDLE"): score+=1
    if session in ("LONDON","NEW_YORK"): score+=1
    if session in ("PRE_LONDON","PRE_NY"): score+=1
    if session == "SILVER_BULLET": score+=2
    if sb: score+=1
    if _is_good_session_pair(symbol, session): score+=1
    if adx_ok: score+=1
    if amd_ok: score+=2
    return score


def _m1_trigger(df_m1, trend) -> str:
    if df_m1 is None or len(df_m1)<5: return ""
    c = df_m1.iloc[-2]
    fvgs = ind.get_fvg(df_m1, trend)
    if fvgs:
        f=fvgs[0]
        if trend=="BULLISH" and c["close"]>=f["bottom"]: return "FVG"
        if trend=="BEARISH" and c["close"]<=f["top"]: return "FVG"
    liq = ind.get_liquidity_levels(df_m1, lookback=10)
    if trend=="BULLISH" and liq["sell_side"]:
        rl=liq["sell_side"][-1]
        if c["low"]<rl and c["close"]>rl: return "LIQ"
    elif trend=="BEARISH" and liq["buy_side"]:
        rh=liq["buy_side"][-1]
        if c["high"]>rh and c["close"]<rh: return "LIQ"
    if trend=="BULLISH" and c["close"]>c["open"]: return "CANDLE"
    if trend=="BEARISH" and c["close"]<c["open"]: return "CANDLE"
    return ""


def _m1_trigger_confirmed(df_m1, trend) -> str:
    if df_m1 is None or len(df_m1) < 6:
        return _m1_trigger(df_m1, trend)
    c1, c2 = df_m1.iloc[-2], df_m1.iloc[-3]
    if trend=="BULLISH":
        two_ok = c1["close"]>c1["open"] and c2["close"]>c2["open"]
    else:
        two_ok = c1["close"]<c1["open"] and c2["close"]<c2["open"]
    if not two_ok:
        log_event("INFO", "ICT: M1 2-candle confirm fail.")
        return ""
    return _m1_trigger(df_m1, trend)


_break_retest_state = {}

def check_break_retest(symbol, df_m15, trend, zone) -> bool:
    global _break_retest_state
    if df_m15 is None or len(df_m15) < 3 or not zone:
        return False
    state = _break_retest_state.get(symbol, {})
    if not state or state.get("trend") != trend:
        _break_retest_state[symbol] = {"trend":trend,"top":zone["top"],
                                       "bottom":zone["bottom"],"bars_waited":0}
        log_event("INFO", f"ICT [{symbol}]: Break-Retest wait shuru.")
        return False
    state["bars_waited"] += 1
    if state["bars_waited"] > config.BREAK_RETEST_WINDOW:
        log_event("INFO", f"ICT [{symbol}]: Retest window expire.")
        _break_retest_state.pop(symbol, None)
        return False
    c = df_m15.iloc[-2]
    top, bottom = state["top"], state["bottom"]
    if trend == "BULLISH":
        touched = c["low"]<=top and c["close"]>bottom
        wick = (min(c["open"],c["close"])-c["low"]) > abs(c["close"]-c["open"])*0.8
        if touched and (wick or c["close"]>c["open"]):
            log_event("INFO", f"ICT [{symbol}]: Retest confirmed!")
            _break_retest_state.pop(symbol, None)
            return True
    elif trend == "BEARISH":
        touched = c["high"]>=bottom and c["close"]<top
        wick = (c["high"]-max(c["open"],c["close"])) > abs(c["close"]-c["open"])*0.8
        if touched and (wick or c["close"]<c["open"]):
            log_event("INFO", f"ICT [{symbol}]: Retest confirmed!")
            _break_retest_state.pop(symbol, None)
            return True
    return False


_re_entry_state = {}

def set_re_entry_state(symbol, trend, zone):
    _re_entry_state[symbol] = {"trend":trend,"zone":zone,"count":0}

def clear_re_entry_state(symbol):
    _re_entry_state.pop(symbol, None)


def generate_ict_signal(symbol, df_m15, df_m5, df_m1, point, df_h1=None) -> dict:
    no_trade = {"signal":"NO_TRADE","symbol":symbol,"entry":0,"sl":0,
                "tp1":0,"tp2":0,"tp3":0,"comment":""}

    if _is_friday_cutoff():
        log_event("INFO", f"ICT [{symbol}]: Friday cutoff."); return no_trade

    # V7.5: Session ab BLOCKING nahi — bonus hai
    kz = is_kill_zone()
    if kz["active"]:
        session = kz["name"]
        log_event("INFO", f"ICT [{symbol}]: Session={session} (bonus milega)")
    else:
        session = "OFF_SESSION"
        log_event("INFO", f"ICT [{symbol}]: Off-session — trade phir bhi possible (no bonus).")

    m15_trend = _get_trend_bos(df_m15, df_m5, df_h1)
    if m15_trend == "NONE":
        log_event("INFO", f"ICT [{symbol}]: BOS trend unclear."); return no_trade

    log_event("INFO", f"ICT [{symbol}]: KZ={session} Trend={m15_trend}")

    if not _check_adx(df_m15):
        log_event("INFO", f"ICT [{symbol}]: ADX low."); return no_trade

    if not _check_momentum(df_h1, m15_trend):
        return no_trade

    zone = _find_quality_zone(df_m15, df_m5, m15_trend, point)
    if not zone:
        log_event("INFO", f"ICT [{symbol}]: No quality zone."); return no_trade

    current = df_m5.iloc[-2]["close"] if df_m5 is not None and len(df_m5)>2 \
              else df_m15.iloc[-2]["close"]

    if not _is_ote_entry(current, zone, m15_trend):
        log_event("INFO", f"ICT [{symbol}]: OTE deep nahi — Wait.")
        return no_trade

    if not _check_pdh_pdl(df_m15, m15_trend, current, point):
        return no_trade

    # V7.4: Break-Retest ab BONUS hai, mandatory nahi
    retest_ok = check_break_retest(symbol, df_m15, m15_trend, zone)
    if not retest_ok:
        log_event("INFO", f"ICT [{symbol}]: Retest nahi — bonus na milega, aage badho.")

    trig_type = _m1_trigger_confirmed(df_m1, m15_trend)
    if not trig_type:
        log_event("INFO", f"ICT [{symbol}]: M1 trigger nahi."); return no_trade

    sb     = is_silver_bullet()
    amd_ok = _check_amd(df_m15, m15_trend)
    score  = _calc_score(m15_trend, m15_trend, zone, trig_type, session,
                         symbol, sb, True, amd_ok)
    if retest_ok:
        score += 3   # Retest confirm bonus
    log_event("INFO", f"ICT [{symbol}]: Score={score}/{MIN_SCORE} AMD={amd_ok} Retest={retest_ok}")
    if score < MIN_SCORE:
        log_event("INFO", f"ICT [{symbol}]: Score low."); return no_trade

    entry = df_m1.iloc[-2]["close"] if df_m1 is not None and len(df_m1)>2 else current
    sl_info = _calc_sl_atr(df_m15, m15_trend, entry, point)
    sl, sl_size = sl_info["sl"], sl_info["size"]
    log_event("INFO", f"ICT [{symbol}]: ATR={sl_info['atr']:.5f} SL_size={sl_size:.5f}")

    zone_type = zone['type'] + ("_AMD" if amd_ok else "")

    if m15_trend == "BULLISH":
        tp1 = entry + sl_size*1.0
        tp2 = entry + sl_size*2.0
        tp3 = entry + sl_size*config.RR_FINAL
        sig = "BUY"
    else:
        tp1 = entry - sl_size*1.0
        tp2 = entry - sl_size*2.0
        tp3 = entry - sl_size*config.RR_FINAL
        sig = "SELL"

    comment = f"ICT_{sig}_{symbol}_{zone_type}_S{score}"
    log_event("INFO", f"ICT {sig} [{symbol}] E:{entry:.5f} SL:{sl:.5f} TP3:{tp3:.5f}")
    return {"signal":sig,"symbol":symbol,"entry":entry,"sl":sl,
            "tp1":tp1,"tp2":tp2,"tp3":tp3,"comment":comment,
            "score":score,"zone":zone}
