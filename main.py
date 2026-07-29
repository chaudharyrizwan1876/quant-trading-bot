# ============================================================
#  main.py — GoldBot V8.4 — GOLD ONLY
#  NEW: SL ab risk_manager.calculate_lot_and_sl() se aata hai —
#  jo 1% risk cap enforce karta hai (SL distance khud shrink
#  hoti hai agar min_lot pe bhi risk zyada bane).
# ============================================================

import time
import config
from market_data import mt5_connector as mt5c
from strategies import gold_hybrid as strategy_gold
from strategies import amd as strategy_amd
from strategies import silver_bullet as strategy_silver_bullet
from strategies import scalper_momentum
from news import news_reader
from execution import trade_manager
from risk import risk_manager as rm
from logger import log_event


def _finalize_sl_tp_broker_min(symbol: str, result: dict, entry: float):
    """
    Broker ke minimum stop-level ke hisaab se SL/TP ko safe
    rakhta hai (yeh risk-cap SE ALAG hai — yeh sirf MT5 ke
    "Invalid stops" error se bachata hai).
    """
    sig = result.get("signal")
    if sig not in ("BUY", "SELL"):
        return
    old_sl = result.get("sl", 0)
    if old_sl == 0 or entry == 0:
        return
    old_sl_size = abs(entry - old_sl)
    if old_sl_size <= 0:
        return

    min_dist = mt5c.get_min_stop_distance(symbol)
    if old_sl_size >= min_dist:
        return

    is_buy = (sig == "BUY")
    new_sl = entry - min_dist if is_buy else entry + min_dist
    scale  = min_dist / old_sl_size

    log_event("INFO",
        f"[{symbol}] SL broker-minimum se tight thi — "
        f"({old_sl_size:.5f} < {min_dist:.5f}) widen kar raha hoon."
    )
    result["sl"] = new_sl
    for key in ("tp1", "tp2", "tp3"):
        if key in result and result[key]:
            old_tp = result[key]
            result[key] = entry + (old_tp - entry) * scale


def _apply_risk_cap(symbol: str, result: dict, entry: float):
    """
    V8.5 CORE FIX — 2 layer protection:

    LAYER 1 (NEW): Absolute hard ceiling — SL distance kabhi
    config.MAX_SL_DOLLAR_GOLD se zyada nahi ho sakti. Yeh
    SABSE PEHLE lagta hai, ATR/strategy kuch bhi bole.

    LAYER 2: 1% equity risk cap — agar min_lot pe bhi risk
    zyada bane (chota SL ke bawajood), SL aur chota hota hai.
    """
    sig = result.get("signal")
    if sig not in ("BUY", "SELL"):
        return

    is_buy = (sig == "BUY")
    old_sl = result["sl"]
    old_sl_size = abs(entry - old_sl)
    if old_sl_size <= 0:
        return

    # ── LAYER 1: Absolute $ cap — sabse pehle ──
    if "XAU" in symbol.upper() and old_sl_size > config.MAX_SL_DOLLAR_GOLD:
        capped_sl_size = config.MAX_SL_DOLLAR_GOLD
        capped_sl = entry - capped_sl_size if is_buy else entry + capped_sl_size
        scale = capped_sl_size / old_sl_size

        log_event("INFO",
            f"[{symbol}] SL ABSOLUTE CAP! {old_sl_size:.2f} > "
            f"max ${config.MAX_SL_DOLLAR_GOLD} → SL {old_sl:.3f} → {capped_sl:.3f} "
            f"(TP proportionally scale)"
        )

        result["sl"] = capped_sl
        for key in ("tp1", "tp2", "tp3"):
            if key in result and result[key]:
                old_tp = result[key]
                result[key] = entry + (old_tp - entry) * scale

        old_sl = capped_sl
        old_sl_size = capped_sl_size

    # ── LAYER 2: 1% equity risk cap (SL aur chota ho sakta hai) ──

    calc = rm.calculate_lot_and_sl(symbol, old_sl, entry, is_buy)
    result["lot"] = calc["lot"]

    if calc["was_capped"]:
        new_sl = calc["sl_price"]
        scale  = calc["sl_distance"] / old_sl_size

        log_event("INFO",
            f"[{symbol}] RISK CAP applied — SL {old_sl:.3f} → {new_sl:.3f} "
            f"(TP bhi proportionally scale ho raha hai, RR same rahega)"
        )

        result["sl"] = new_sl
        for key in ("tp1", "tp2", "tp3"):
            if key in result and result[key]:
                old_tp = result[key]
                result[key] = entry + (old_tp - entry) * scale


def run():
    log_event("INFO", "========== GoldBot V9 (GOLD ONLY — confidence-gated) Starting ==========")

    if not mt5c.connect():
        log_event("ERROR", "MT5 connection fail.")
        return

    log_event("INFO", f"Symbol: {config.SYMBOL_GOLD}")
    _mode = getattr(config, "STRATEGY_MODE", "momentum")
    if _mode == "momentum":
        log_event("INFO", "Strategy: M5 Momentum Scalper (backtest winner) "
                          f"| time-stop {getattr(config,'MAX_HOLD_MINUTES',0)}min")
    else:
        log_event("INFO", "Strategies: Gold Hybrid + AMD + Silver Bullet (swing mode)")
    log_event("INFO", f"Risk : {config.RISK_PERCENT*100:.0f}% hard cap, "
                      f"scaled down to {getattr(config,'RISK_PERCENT_MIN',config.RISK_PERCENT)*100:.1f}% "
                      f"by confidence")
    log_event("INFO", f"Confidence gate: {'ON' if getattr(config,'CONFIDENCE_GATING_ENABLED',True) else 'OFF'} "
                      f"(min {getattr(config,'MIN_CONFIDENCE',66.0):.0f}%)")
    log_event("INFO", f"Circuit breaker: {getattr(config,'MAX_CONSECUTIVE_LOSSES',3)} consecutive losses")
    log_event("INFO", f"TP   : 1:{config.RR_FINAL:.0f} | Partial: {config.PARTIAL_CLOSE_PCT*100:.0f}% at 1:{config.PARTIAL_CLOSE_RR}")

    if config.NEWS_ENABLED:
        news_reader.print_todays_news()

    try:
        while True:

            if rm.is_daily_loss_limit_hit():
                log_event("WARNING", "Daily loss limit hit — Trading paused.")
                try: trade_manager.manage_open_trades()
                except Exception as e: log_event("ERROR", f"Trade manager: {e}")
                time.sleep(60)
                continue

            if config.NEWS_ENABLED and news_reader.is_high_impact_soon(config.NEWS_PAUSE_BEFORE_MINS):
                log_event("INFO", "High impact news soon — Pause.")
                try: trade_manager.manage_open_trades()
                except Exception as e: log_event("ERROR", f"Trade manager: {e}")
                time.sleep(config.CHECK_INTERVAL_SECONDS)
                continue

            candidates = []

            if getattr(config, "STRATEGY_MODE", "momentum") == "momentum":
                getters = (("GOLD-MOM", _get_momentum_signal),)
            else:
                getters = (
                    ("GOLD",     _get_gold_signal),
                    ("GOLD-AMD", lambda: _get_amd_signal(config.SYMBOL_GOLD)),
                    ("GOLD-SB",  lambda: _get_silver_bullet_signal(config.SYMBOL_GOLD)),
                )

            for label, getter in getters:
                try:
                    result = getter()
                    if result and result["signal"] != "NO_TRADE":
                        cand = _evaluate_candidate(config.SYMBOL_GOLD, result)
                        candidates.append(cand)
                        conf = cand["confidence"]
                        log_event("INFO",
                            f"[{config.SYMBOL_GOLD}] {label} candidate — "
                            f"confidence:{conf.confidence:.0f}% grade:{conf.grade} "
                            f"pass:{conf.passed} score:{cand['score']:.1f}")
                        if conf.reasons:
                            log_event("INFO", f"[{label}] Reasons: " + "; ".join(conf.reasons))
                        if conf.penalties:
                            log_event("INFO", f"[{label}] Penalties: " + "; ".join(conf.penalties))
                except Exception as e:
                    log_event("ERROR", f"[{label}] Signal error: {e}")

            if candidates:
                # Rank by confidence (primary), score as tiebreaker
                candidates.sort(key=lambda c: (c["confidence"].confidence, c["score"]),
                                reverse=True)
                best = candidates[0]["confidence"]
                log_event("INFO",
                    f"Total candidates: {len(candidates)} — "
                    f"Best: {best.confidence:.0f}% ({best.grade})")
                _execute_candidates(candidates)
            else:
                log_event("INFO", "No signals — Wait...")

            try:
                trade_manager.manage_open_trades()
            except Exception as e:
                log_event("ERROR", f"Trade manager: {e}")

            time.sleep(config.CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log_event("INFO", "Bot band kiya (Ctrl+C).")
    finally:
        mt5c.disconnect()
        log_event("INFO", "========== GoldBot Stopped ==========")


def _get_gold_signal() -> dict:
    sym = config.SYMBOL_GOLD
    price = mt5c.get_price(sym)
    if price is None: return None
    print(f"\n{sym} — Bid:{price['bid']:.3f}  Ask:{price['ask']:.3f}")

    if not rm.can_open_trade(sym):
        return None

    point  = mt5c.get_symbol_point(sym)
    df_d1  = mt5c.get_candles(config.TIMEFRAME_D1,  config.CANDLE_D1,  sym)
    df_h1  = mt5c.get_candles(config.TIMEFRAME_H1,  config.CANDLE_H1,  sym)
    df_m30 = mt5c.get_candles(config.TIMEFRAME_M30, config.CANDLE_M30, sym)
    df_m15 = mt5c.get_candles(config.TIMEFRAME_M15, config.CANDLE_M15, sym)
    df_m5  = mt5c.get_candles(config.TIMEFRAME_M5,  config.CANDLE_M5,  sym)
    df_m1  = mt5c.get_candles(config.TIMEFRAME_M1,  config.CANDLE_M1,  sym)

    if any(df is None for df in [df_h1, df_m30, df_m15, df_m5, df_m1]):
        log_event("WARNING", f"[{sym}] Candles nahi milin.")
        return None

    news_sig = news_reader.get_news_signal(sym) if config.NEWS_ENABLED else None

    result = strategy_gold.generate_gold_signal(
        df_h1=df_h1, df_m30=df_m30, df_m15=df_m15,
        df_m5=df_m5, df_m1=df_m1, point=point,
        df_d1=df_d1, news_sig=news_sig
    )

    if result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp_broker_min(sym, result, entry)
        _apply_risk_cap(sym, result, entry)   # ← Asal 1% cap yahan lagta hai

    return result


def _get_momentum_signal() -> dict:
    """
    M5 momentum/breakout scalper (backtest winner). M5 primary +
    M15 context. Baaki getters jaisa hi finalize/risk-cap flow.
    """
    sym = config.SYMBOL_GOLD
    price = mt5c.get_price(sym)
    if price is None:
        return None
    print(f"\n{sym} — Bid:{price['bid']:.3f}  Ask:{price['ask']:.3f}")

    if not rm.can_open_trade(sym):
        return None

    point  = mt5c.get_symbol_point(sym)
    df_m15 = mt5c.get_candles(config.TIMEFRAME_M15, config.CANDLE_M15, sym)
    df_m5  = mt5c.get_candles(config.TIMEFRAME_M5,  config.CANDLE_M5,  sym)
    df_m1  = mt5c.get_candles(config.TIMEFRAME_M1,  config.CANDLE_M1,  sym)

    if df_m5 is None:
        log_event("WARNING", f"[{sym}] M5 candles nahi milin.")
        return None

    result = scalper_momentum.generate_scalp_momentum_signal(
        df_m15=df_m15, df_m5=df_m5, df_m1=df_m1, point=point
    )

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp_broker_min(sym, result, entry)
        _apply_risk_cap(sym, result, entry)

    return result


def _get_amd_signal(sym: str) -> dict:
    price = mt5c.get_price(sym)
    if price is None: return None
    if not rm.can_open_trade(sym): return None

    point  = mt5c.get_symbol_point(sym)
    df_m15 = mt5c.get_candles(config.TIMEFRAME_M15, config.CANDLE_M15, sym)
    if df_m15 is None: return None

    result = strategy_amd.generate_amd_signal(sym, df_m15, point)

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp_broker_min(sym, result, entry)
        _apply_risk_cap(sym, result, entry)

    return result


def _get_silver_bullet_signal(sym: str) -> dict:
    if not strategy_silver_bullet.is_silver_bullet_window():
        return None

    price = mt5c.get_price(sym)
    if price is None: return None
    if not rm.can_open_trade(sym): return None

    point = mt5c.get_symbol_point(sym)
    df_m5 = mt5c.get_candles(config.TIMEFRAME_M5, config.CANDLE_M5, sym)
    if df_m5 is None: return None

    result = strategy_silver_bullet.generate_silver_bullet_signal(sym, df_m5, point)

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp_broker_min(sym, result, entry)
        _apply_risk_cap(sym, result, entry)

    return result


def _compute_rr(result: dict) -> float:
    entry = result.get("entry", 0)
    sl    = result.get("sl", 0)
    tp    = result.get("tp3") or result.get("tp1") or 0
    if entry <= 0 or sl <= 0 or tp <= 0:
        return 0.0
    sl_size = abs(entry - sl)
    if sl_size <= 0:
        return 0.0
    return abs(entry - tp) / sl_size


def _evaluate_candidate(symbol: str, result: dict) -> dict:
    """
    Rule-engine result ko decision layer se guzaarta hai:
    factors → bounded confidence % + structured reasons.
    Returns candidate dict for ranking/execution.
    """
    import ai.confidence as ai_conf

    memory_adj = 0.0
    try:
        from memory import trade_memory as tm
        memory_adj += tm.get_adaptive_score(symbol, result.get("comment", ""))
        memory_adj += tm.get_hour_adaptive_score(symbol)
    except Exception:
        pass

    rr   = _compute_rr(result)
    conf = ai_conf.evaluate(result.get("factors", {}), rr=rr, memory_adj=memory_adj)

    # Legacy numeric score — sirf tiebreaker/log ke liye rakha hai
    score = rm.score_signal(symbol, result) + memory_adj

    return {"confidence": conf, "symbol": symbol, "result": result, "score": score}


def _execute_candidates(candidates: list):
    for cand in candidates:
        symbol = cand["symbol"]
        result = cand["result"]
        conf   = cand["confidence"]

        if rm.is_daily_loss_limit_hit():
            log_event("WARNING", "Daily limit — stopping execution.")
            break

        # ── Confidence gate — asal "quality over quantity" filter ──
        if getattr(config, "CONFIDENCE_GATING_ENABLED", True) and not conf.passed:
            log_event("INFO",
                f"[{symbol}] Skipped — confidence {conf.confidence:.0f}% "
                f"< threshold {getattr(config, 'MIN_CONFIDENCE', 66.0):.0f}% "
                f"(grade {conf.grade}).")
            continue

        if not rm.can_open_trade(symbol):
            continue

        try:
            from memory import trade_memory as tm
            if tm.is_pattern_blocked(symbol, result.get("comment","")):
                continue
        except Exception:
            pass

        # Confidence-scaled position sizing — higher conviction = bigger
        # size (up to the 1% hard cap), marginal setups sized down.
        lot = result.get("lot", config.LOT_SIZE_GOLD)
        try:
            entry_px  = result.get("entry", 0)
            is_buy    = result["signal"] == "BUY"
            risk_frac = rm.risk_fraction_for_confidence(conf.confidence)
            scaled    = rm.calculate_lot_and_sl(symbol, result["sl"], entry_px,
                                                is_buy, risk_pct=risk_frac)
            lot = scaled["lot"]
            log_event("INFO",
                f"[{symbol}] Size scaled to {risk_frac*100:.2f}% risk "
                f"(conf {conf.confidence:.0f}%) → lot {lot}")
        except Exception as e:
            log_event("WARNING", f"[{symbol}] Confidence sizing fallback: {e}")

        sig     = result["signal"]
        tp      = result.get("tp3") or result.get("tp1")
        comment = f"{result['comment']}_{conf.as_comment_suffix()}"

        if sig == "BUY":
            log_event("INFO",
                f"[{symbol}] BUY Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} "
                f"Conf:{conf.confidence:.0f}%({conf.grade})")
            order = mt5c.open_buy_order(symbol=symbol, sl_price=result["sl"],
                                        tp_price=tp, lot=lot, comment=comment)
            if order:
                log_event("INFO", f"[{symbol}] BUY OK Ticket:{order.order}")
            else:
                log_event("ERROR", f"[{symbol}] BUY fail.")

        elif sig == "SELL":
            log_event("INFO",
                f"[{symbol}] SELL Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} "
                f"Conf:{conf.confidence:.0f}%({conf.grade})")
            order = mt5c.open_sell_order(symbol=symbol, sl_price=result["sl"],
                                         tp_price=tp, lot=lot, comment=comment)
            if order:
                log_event("INFO", f"[{symbol}] SELL OK Ticket:{order.order}")
            else:
                log_event("ERROR", f"[{symbol}] SELL fail.")


if __name__ == "__main__":
    run()
