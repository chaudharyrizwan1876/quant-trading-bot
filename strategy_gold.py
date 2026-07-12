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

    trend = _get_trend_bos(df_h1, df_m30)
    if trend == "NONE":
        log_event("INFO","GOLD: BOS trend unclear."); return no_trade

    log_event("INFO", f"GOLD: Trend={trend} Session={session}")

    m15_struct = ind.get_market_structure(df_m15)
    m15_trend  = m15_struct["trend"]
    if m15_trend != "NONE" and m15_trend != trend:
        log_event("INFO", f"GOLD: M15={m15_trend} conflict."); return no_trade

    if not _check_adx(df_m15):
        log_event("INFO","GOLD: ADX low — ranging."); return no_trade

    current = df_m15.iloc[-2]["close"] if df_m15 is not None else 0
    if not _check_d1_levels(df_d1, trend, current):
        return no_trade

    if not _check_momentum(df_h1, trend):
        return no_trade

    news_dir = None
    if config.NEWS_TRADE_ENABLED and news_sig and \
            news_sig.get("signal") != "NO_TRADE":
        news_dir = news_sig["signal"]
        expected = "BUY" if trend == "BULLISH" else "SELL"
        if news_dir != expected: news_dir = None

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
    m1_trigger = _m1_entry_confirmed(df_m1, trend)

    # V7.3: AMD bonus check
    amd_ok = _check_amd(df_m15, trend)

    score = _calc_score(trend, m15_trend, m15_zone, m5_confirm,
                        m1_trigger, news_dir, session, amd_ok)
    if retest_ok:
        score += 3   # Retest confirm bonus
    log_event("INFO", f"GOLD: Score={score}/{MIN_SCORE} AMD={amd_ok} Retest={retest_ok}")
    if score < MIN_SCORE:
        log_event("INFO", f"GOLD: Score low — Skip."); return no_trade

    zone_ok  = m15_zone is not None
    entry_ok = (zone_ok or news_dir is not None) and m1_trigger
    if not entry_ok:
        log_event("INFO","GOLD: Entry conditions fail."); return no_trade

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
        tp3 = round(entry + sl_size*config.RR_FINAL, 3)
        sig = "BUY"
    else:
        tp1 = round(entry - sl_size*1.0, 3)
        tp2 = round(entry - sl_size*2.0, 3)
        tp3 = round(entry - sl_size*config.RR_FINAL, 3)
        sig = "SELL"

    log_event("INFO",
        f"GOLD {sig} E:{entry:.3f} SL:{sl:.3f} TP1:{tp1:.3f} "
        f"TP2:{tp2:.3f} TP3:{tp3:.3f} Score:{score}")
    return {"signal":sig,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,
            "comment":f"GOLD_{sig}_{zone_type}_S{score}","score":score}


# ─────────────────────────────────────────────
#  V7.3: SESSION — Pre-London, London, Pre-NY, NY, Silver Bullet
# ─────────────────────────────────────────────

def _get_session() -> str:
    h = datetime.now(timezone.utc).hour

    if config.KILL_ZONE_PRE_LONDON_START <= h < config.KILL_ZONE_PRE_LONDON_END:
        return "PRE_LONDON"
    if 8 <= h < 12: return "LONDON"
    if config.KILL_ZONE_PRE_NY_START <= h < config.KILL_ZONE_PRE_NY_END:
        return "PRE_NY"
    if 13 <= h < 17: return "NEW_YORK"

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


def _get_trend_bos(df_h1, df_m30) -> str:
    def bos(df):
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

    h1t, m30t = bos(df_h1), bos(df_m30)
    log_event("INFO", f"GOLD: H1_BOS={h1t} M30_BOS={m30t}")
    if h1t==m30t and h1t!="NONE": return h1t
    if h1t!="NONE" and m30t=="NONE": return h1t
    if m30t!="NONE" and h1t=="NONE": return m30t
    if h1t!="NONE": return h1t
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
        ob=obs[0]
        if ind.price_in_zone(current, ob["top"], ob["bottom"], BUF*3):
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


def _check_momentum(df_h1, trend) -> bool:
    rsi = _calc_rsi(df_h1, config.RSI_PERIOD)
    log_event("INFO", f"GOLD: H1 RSI={rsi:.1f}")
    if trend == "BULLISH" and rsi >= config.RSI_OVERBOUGHT:
        log_event("INFO", "GOLD: RSI overbought — Skip."); return False
    if trend == "BEARISH" and rsi <= config.RSI_OVERSOLD:
        log_event("INFO", "GOLD: RSI oversold — Skip."); return False
    return True


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


def _calc_score(trend, m15_trend, zone, m5c, m1t, news_dir, session, amd_ok) -> int:
    s=0
    if trend!="NONE": s+=1
    if m15_trend==trend: s+=1
    if zone:
        zt=zone.get("type","")
        if "OB" in zt: s+=2
        elif "FVG" in zt: s+=1
        elif "LIQ" in zt: s+=1
    if m5c: s+=1
    if m1t: s+=1
    if news_dir: s+=1
    if session in ("LONDON","NEW_YORK"): s+=1
    if session in ("PRE_LONDON","PRE_NY"): s+=1
    if session == "SILVER_BULLET": s+=2
    if amd_ok: s+=2
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
