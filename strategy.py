# ============================================================
#  strategy.py — Liquidity Sweep (GOLD ONLY — XAUUSDm)
#  V4.2 — SL/TP fixed: Gold price-based (not points)
# ============================================================
#
#  Case A:  C4 seedhi direction     | SL=C3 low/high | TP=1:2
#  Case B:  C4 ny C3 liquidity li   | C4 mid entry   | TP=1:3
#  Case C1: C3 ke baad 7pip wait    | SL=C3 low/high | TP=1:2
#  Case C2: C2 liquidity li         | C2 mid entry   | TP=1:2
#
#  Pattern 1 — Sweep:    lows neeche / highs upar
#  Pattern 2 — Rejection: lows upar  / highs neeche
# ============================================================

import config
import indicators as ind
from logger import log_event

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────
_waiting_case = ""
_case_data    = {}
_active_ob    = None
_ob_direction = ""
CASE_C1_PIPS  = 7


# ══════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════

def generate_signal(df_m15, df_h1, point: float,
                    df_m5=None, df_m30=None) -> dict:

    global _active_ob, _ob_direction
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}

    h1_struct = ind.get_market_structure(df_h1)
    h1_trend  = h1_struct["trend"]
    if h1_trend == "NONE":
        log_event("INFO", "H1: Trend unclear — No trade.")
        _reset_all()
        return no_trade

    log_event("INFO", f"H1: {h1_trend} | {h1_struct['structure']}")

    m30_struct = ind.get_market_structure(df_m30)
    m30_trend  = m30_struct["trend"]

    return _liquidity_sweep(df_m15, df_m30, df_h1, h1_trend, m30_trend, point)


# ══════════════════════════════════════════════
#  LIQUIDITY SWEEP
# ══════════════════════════════════════════════

def _liquidity_sweep(df_m15, df_m30, df_h1, h1_trend, m30_trend, point) -> dict:
    global _waiting_case, _case_data
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}

    if _waiting_case and _case_data:
        if _case_data.get("trend") != h1_trend:
            log_event("INFO", "LIQ: Trend flip — cancel.")
            _reset_liq_state()
            return no_trade
        if _waiting_case == "B":  return _check_case_b(df_m15)
        if _waiting_case == "C1": return _check_case_c1(df_m15, point)
        if _waiting_case == "C2": return _check_case_c2(df_m15)

    for df_check, label in [(df_m15,"M15"),(df_m30,"M30"),(df_h1,"H1")]:
        p = _find_pattern(df_check, h1_trend, point)
        if p:
            log_event("INFO", f"LIQ: Pattern mila [{label}] [{p.get('pattern','')}]")
            return _process_pattern(p, df_check, h1_trend, point, label)

    log_event("INFO", "LIQ: Pattern nahi mila.")
    return no_trade


def _process_pattern(pattern, df, trend, point, tf_label) -> dict:
    global _waiting_case, _case_data
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}

    c2       = pattern["c2"]
    c3       = pattern["c3"]
    c3_idx   = pattern["c3_idx"]
    pat_type = pattern.get("pattern","P1_SWEEP")
    closed   = df.iloc[:-1].reset_index(drop=True)

    if c3_idx + 1 >= len(closed):
        log_event("INFO", f"LIQ [{tf_label}]: C4 nahi aayi.")
        return no_trade

    c4  = closed.iloc[c3_idx + 1]
    buf = config.GOLD_SL_BUFFER   # Direct price buffer ($2)

    if trend == "BULLISH":
        c3_close = c3["close"]
        c3_low   = c3["low"]
        c2_low   = c2["low"]
        c2_mid   = (c2["open"] + c2["close"]) / 2

        # Case A — C4 seedhi BUY
        if c4["close"] > c3_close:
            entry   = c3_close
            sl      = c3_low - buf
            sl_size = entry - sl
            if sl_size <= 0: return no_trade
            tp1 = entry + sl_size * config.GOLD_TP1_RR
            tp2 = entry + sl_size * config.GOLD_TP2_RR
            log_event("INFO",
                f"LIQ [{tf_label}] {pat_type} Case A BUY — "
                f"E:{entry:.3f} SL:{sl:.3f} TP1:{tp1:.3f}"
            )
            _reset_liq_state()
            return _sig("BUY", entry, sl, tp1, tp2,
                        f"LIQ_A_{pat_type}_BUY_{tf_label}")

        # Case C1 — 7 pip upar
        c3p7 = c3_close + (CASE_C1_PIPS * 0.1)  # Gold: 7 pips = $0.70
        if c4["high"] >= c3p7 and c4["close"] > c3_close:
            entry   = c3p7
            sl      = c3_low - buf
            sl_size = entry - sl
            if sl_size <= 0: return no_trade
            tp1 = entry + sl_size * config.GOLD_TP1_RR
            tp2 = entry + sl_size * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("BUY", entry, sl, tp1, tp2,
                        f"LIQ_C1_{pat_type}_BUY_{tf_label}")

        # Case B — C4 ny C3 liquidity li
        if c4["low"] < c3_low:
            _waiting_case = "B"
            _case_data = {
                "trend": trend, "direction": "BUY",
                "c4_low": c4["low"],
                "c4_mid": (c4["open"] + c4["close"]) / 2,
                "pat_type": pat_type, "tf": tf_label
            }
            log_event("INFO", f"LIQ [{tf_label}] Case B BUY wait")
            return no_trade

        # Case C2 — C4 ny C2 liquidity li
        if c4["low"] < c2_low:
            _waiting_case = "C2"
            _case_data = {
                "trend": trend, "direction": "BUY",
                "c2_low": c2_low, "c2_mid": c2_mid,
                "pat_type": pat_type, "tf": tf_label
            }
            log_event("INFO", f"LIQ [{tf_label}] Case C2 BUY wait")
            return no_trade

        # Case C1 wait
        if c4["close"] > c3_close:
            _waiting_case = "C1"
            _case_data = {
                "trend": trend, "direction": "BUY",
                "c3_close": c3_close, "c3_low": c3_low,
                "c2_low": c2_low, "c2_mid": c2_mid,
                "c3_plus_7": c3p7,
                "pat_type": pat_type, "tf": tf_label
            }
            return no_trade

    elif trend == "BEARISH":
        c3_close = c3["close"]
        c3_high  = c3["high"]
        c2_high  = c2["high"]
        c2_mid   = (c2["open"] + c2["close"]) / 2

        # Case A — C4 seedhi SELL
        if c4["close"] < c3_close:
            entry   = c3_close
            sl      = c3_high + buf
            sl_size = sl - entry
            if sl_size <= 0: return no_trade
            tp1 = entry - sl_size * config.GOLD_TP1_RR
            tp2 = entry - sl_size * config.GOLD_TP2_RR
            log_event("INFO",
                f"LIQ [{tf_label}] {pat_type} Case A SELL — "
                f"E:{entry:.3f} SL:{sl:.3f} TP1:{tp1:.3f}"
            )
            _reset_liq_state()
            return _sig("SELL", entry, sl, tp1, tp2,
                        f"LIQ_A_{pat_type}_SELL_{tf_label}")

        # Case C1 — 7 pip neeche
        c3m7 = c3_close - (CASE_C1_PIPS * 0.1)
        if c4["low"] <= c3m7 and c4["close"] < c3_close:
            entry   = c3m7
            sl      = c3_high + buf
            sl_size = sl - entry
            if sl_size <= 0: return no_trade
            tp1 = entry - sl_size * config.GOLD_TP1_RR
            tp2 = entry - sl_size * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("SELL", entry, sl, tp1, tp2,
                        f"LIQ_C1_{pat_type}_SELL_{tf_label}")

        # Case B — C4 ny C3 liquidity li
        if c4["high"] > c3_high:
            _waiting_case = "B"
            _case_data = {
                "trend": trend, "direction": "SELL",
                "c4_high": c4["high"],
                "c4_mid": (c4["open"] + c4["close"]) / 2,
                "pat_type": pat_type, "tf": tf_label
            }
            log_event("INFO", f"LIQ [{tf_label}] Case B SELL wait")
            return no_trade

        # Case C2 — C4 ny C2 liquidity li
        if c4["high"] > c2_high:
            _waiting_case = "C2"
            _case_data = {
                "trend": trend, "direction": "SELL",
                "c2_high": c2_high, "c2_mid": c2_mid,
                "pat_type": pat_type, "tf": tf_label
            }
            log_event("INFO", f"LIQ [{tf_label}] Case C2 SELL wait")
            return no_trade

        # Case C1 wait
        if c4["close"] < c3_close:
            _waiting_case = "C1"
            _case_data = {
                "trend": trend, "direction": "SELL",
                "c3_close": c3_close, "c3_high": c3_high,
                "c2_high": c2_high, "c2_mid": c2_mid,
                "c3_minus_7": c3m7,
                "pat_type": pat_type, "tf": tf_label
            }
            return no_trade

    return no_trade


# ─────────────────────────────────────────────
#  CASE HANDLERS
# ─────────────────────────────────────────────

def _check_case_b(df) -> dict:
    global _waiting_case, _case_data
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}
    if df is None or len(df) < 3: return no_trade

    close    = df.iloc[-2]["close"]
    d        = _case_data["direction"]
    c4_mid   = _case_data["c4_mid"]
    tf       = _case_data.get("tf","")
    pt       = _case_data.get("pat_type","P1")
    buf      = config.GOLD_SL_BUFFER

    if d == "BUY" and close >= c4_mid:
        sl   = _case_data["c4_low"] - buf
        sz   = close - sl
        if sz <= 0: return no_trade
        tp1  = close + sz * config.GOLD_TP1_RR
        tp2  = close + sz * config.GOLD_TP2_RR
        log_event("INFO",
            f"LIQ [{tf}] {pt} Case B BUY — E:{close:.3f} SL:{sl:.3f} TP1:{tp1:.3f}"
        )
        _reset_liq_state()
        return _sig("BUY", close, sl, tp1, tp2, f"LIQ_B_{pt}_BUY_{tf}")

    elif d == "SELL" and close <= c4_mid:
        sl   = _case_data["c4_high"] + buf
        sz   = sl - close
        if sz <= 0: return no_trade
        tp1  = close - sz * config.GOLD_TP1_RR
        tp2  = close - sz * config.GOLD_TP2_RR
        log_event("INFO",
            f"LIQ [{tf}] {pt} Case B SELL — E:{close:.3f} SL:{sl:.3f} TP1:{tp1:.3f}"
        )
        _reset_liq_state()
        return _sig("SELL", close, sl, tp1, tp2, f"LIQ_B_{pt}_SELL_{tf}")

    log_event("INFO", f"LIQ Case B wait — {close:.3f} vs {c4_mid:.3f}")
    return no_trade


def _check_case_c1(df, point) -> dict:
    global _waiting_case, _case_data
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}
    if df is None or len(df) < 3: return no_trade

    d   = _case_data["direction"]
    tf  = _case_data.get("tf","")
    pt  = _case_data.get("pat_type","P1")
    ch  = df.iloc[-1]["high"]
    cl  = df.iloc[-1]["low"]
    cc  = df.iloc[-2]["close"]
    buf = config.GOLD_SL_BUFFER

    if d == "BUY":
        c3p7   = _case_data.get("c3_plus_7", 0)
        c2_mid = _case_data["c2_mid"]
        c3_low = _case_data["c3_low"]
        c2_low = _case_data["c2_low"]

        if ch >= c3p7 and cc > _case_data["c3_close"]:
            sl  = c3_low - buf
            sz  = c3p7 - sl
            if sz <= 0: return no_trade
            tp1 = c3p7 + sz * config.GOLD_TP1_RR
            tp2 = c3p7 + sz * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("BUY", c3p7, sl, tp1, tp2, f"LIQ_C1a_{pt}_BUY_{tf}")

        if cl < c2_low:
            _case_data["c1b_active"] = True
        if _case_data.get("c1b_active") and cc >= c2_mid:
            sl  = c2_low - buf
            sz  = cc - sl
            if sz <= 0: return no_trade
            tp1 = cc + sz * config.GOLD_TP1_RR
            tp2 = cc + sz * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("BUY", cc, sl, tp1, tp2, f"LIQ_C1b_{pt}_BUY_{tf}")

    elif d == "SELL":
        c3m7   = _case_data.get("c3_minus_7", 0)
        c2_mid = _case_data["c2_mid"]
        c3_hi  = _case_data["c3_high"]
        c2_hi  = _case_data["c2_high"]

        if cl <= c3m7 and cc < _case_data["c3_close"]:
            sl  = c3_hi + buf
            sz  = sl - c3m7
            if sz <= 0: return no_trade
            tp1 = c3m7 - sz * config.GOLD_TP1_RR
            tp2 = c3m7 - sz * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("SELL", c3m7, sl, tp1, tp2, f"LIQ_C1a_{pt}_SELL_{tf}")

        if ch > c2_hi:
            _case_data["c1b_active"] = True
        if _case_data.get("c1b_active") and cc <= c2_mid:
            sl  = c2_hi + buf
            sz  = sl - cc
            if sz <= 0: return no_trade
            tp1 = cc - sz * config.GOLD_TP1_RR
            tp2 = cc - sz * config.GOLD_TP2_RR
            _reset_liq_state()
            return _sig("SELL", cc, sl, tp1, tp2, f"LIQ_C1b_{pt}_SELL_{tf}")

    log_event("INFO", f"LIQ Case C1 wait — {d}")
    return no_trade


def _check_case_c2(df) -> dict:
    global _waiting_case, _case_data
    no_trade = {"signal":"NO_TRADE","entry":0,"sl":0,"tp1":0,"tp2":0,"comment":""}
    if df is None or len(df) < 3: return no_trade

    close  = df.iloc[-2]["close"]
    d      = _case_data["direction"]
    c2_mid = _case_data["c2_mid"]
    tf     = _case_data.get("tf","")
    pt     = _case_data.get("pat_type","P1")
    buf    = config.GOLD_SL_BUFFER

    if d == "BUY" and close >= c2_mid:
        sl  = _case_data["c2_low"] - buf
        sz  = close - sl
        if sz <= 0: return no_trade
        tp1 = close + sz * config.GOLD_TP1_RR
        tp2 = close + sz * config.GOLD_TP2_RR
        _reset_liq_state()
        return _sig("BUY", close, sl, tp1, tp2, f"LIQ_C2_{pt}_BUY_{tf}")

    elif d == "SELL" and close <= c2_mid:
        sl  = _case_data["c2_high"] + buf
        sz  = sl - close
        if sz <= 0: return no_trade
        tp1 = close - sz * config.GOLD_TP1_RR
        tp2 = close - sz * config.GOLD_TP2_RR
        _reset_liq_state()
        return _sig("SELL", close, sl, tp1, tp2, f"LIQ_C2_{pt}_SELL_{tf}")

    log_event("INFO", f"LIQ Case C2 wait — {close:.3f} vs {c2_mid:.3f}")
    return no_trade


# ─────────────────────────────────────────────
#  PATTERN FINDER — Pattern 1 + Pattern 2
# ─────────────────────────────────────────────

def _find_pattern(df, trend, point) -> dict:
    """
    Pattern 1 — Sweep:
      SELL: highs upar jaate rahe
      BUY:  lows neeche jaate rahe

    Pattern 2 — Rejection:
      SELL: highs neeche aate rahe + closes neeche
      BUY:  lows upar aate rahe + closes upar
    """
    if df is None or len(df) < 6:
        return None

    min_wick = config.MIN_WICK_POINTS * point
    closed   = df.iloc[:-1].reset_index(drop=True)

    for i in range(len(closed)-3, max(len(closed)-15, 0), -1):
        if i < 0: break
        c1 = closed.iloc[i]
        c2 = closed.iloc[i+1]
        c3 = closed.iloc[i+2]

        # Pattern 1 — Sweep
        if trend == "BULLISH":
            if (c2["low"] < c1["low"] and c3["low"] < c2["low"]):
                w1 = min(c1["open"],c1["close"]) - c1["low"]
                if w1 >= min_wick:
                    log_event("INFO",
                        f"LIQ P1-SWEEP [BULL] — "
                        f"C1:{c1['time']} C2:{c2['time']} C3:{c3['time']}"
                    )
                    return {"c1":c1,"c2":c2,"c3":c3,
                            "c3_idx":i+2,"pattern":"P1_SWEEP"}

        elif trend == "BEARISH":
            if (c2["high"] > c1["high"] and c3["high"] > c2["high"]):
                w1 = c1["high"] - max(c1["open"],c1["close"])
                if w1 >= min_wick:
                    log_event("INFO",
                        f"LIQ P1-SWEEP [BEAR] — "
                        f"C1:{c1['time']} C2:{c2['time']} C3:{c3['time']}"
                    )
                    return {"c1":c1,"c2":c2,"c3":c3,
                            "c3_idx":i+2,"pattern":"P1_SWEEP"}

        # Pattern 2 — Rejection
        if trend == "BULLISH":
            if (c2["low"]   > c1["low"] and
                c3["low"]   > c2["low"] and
                c2["close"] > c1["close"] and
                c3["close"] > c2["close"]):
                log_event("INFO",
                    f"LIQ P2-REJECTION [BULL] — "
                    f"C1:{c1['time']} C2:{c2['time']} C3:{c3['time']}"
                )
                return {"c1":c1,"c2":c2,"c3":c3,
                        "c3_idx":i+2,"pattern":"P2_REJECTION"}

        elif trend == "BEARISH":
            if (c2["high"]  < c1["high"] and
                c3["high"]  < c2["high"] and
                c2["close"] < c1["close"] and
                c3["close"] < c2["close"]):
                log_event("INFO",
                    f"LIQ P2-REJECTION [BEAR] — "
                    f"C1:{c1['time']} C2:{c2['time']} C3:{c3['time']}"
                )
                return {"c1":c1,"c2":c2,"c3":c3,
                        "c3_idx":i+2,"pattern":"P2_REJECTION"}

    return None


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def _sig(s,e,sl,tp1,tp2,c):
    return {"signal":s,"entry":e,"sl":sl,"tp1":tp1,"tp2":tp2,"comment":c}

def _reset_liq_state():
    global _waiting_case, _case_data
    _waiting_case = ""
    _case_data    = {}

def _reset_all():
    global _active_ob, _ob_direction
    _active_ob    = None
    _ob_direction = ""
    _reset_liq_state()
