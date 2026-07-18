# ============================================================
#  main.py — GoldBot V8.0 — GOLD ONLY
#  Forex pairs nikal diye gaye hain. Sirf XAUUSDm trade hoti
#  hai — 3 parallel strategies ke saath: Gold Hybrid, AMD
#  (standalone), Silver Bullet (standalone).
# ============================================================

import time
import config
import mt5_connector as mt5c
import strategy_gold
import strategy_amd
import strategy_silver_bullet
import news_reader
import trade_manager
import risk_manager as rm
from logger import log_event


def _finalize_sl_tp(symbol: str, result: dict, entry: float):
    """
    SL ko broker ke minimum stop-level ke hisaab se PEHLE
    finalize karo, phir usi final SL se TP recalculate karo
    (proportionally, original RR ratio maintain karke), aur
    TABHI lot calculate hoga.
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
        f"[{symbol}] SL bahut tight thi ({old_sl_size:.5f}) — "
        f"broker minimum ({min_dist:.5f}) tak widen kar raha hoon."
    )

    result["sl"] = new_sl
    for key in ("tp1", "tp2", "tp3"):
        if key in result and result[key]:
            old_tp = result[key]
            result[key] = entry + (old_tp - entry) * scale


def run():
    log_event("INFO", "========== GoldBot V8.0 (GOLD ONLY) Starting ==========")

    if not mt5c.connect():
        log_event("ERROR", "MT5 connection fail.")
        return

    log_event("INFO", f"Symbol: {config.SYMBOL_GOLD} (Forex disabled)")
    log_event("INFO", f"Strategies: Gold Hybrid + AMD + Silver Bullet")
    log_event("INFO", f"Risk : {config.RISK_PERCENT*100:.0f}% per trade (EQUITY)")
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

            # ── Gold Hybrid Strategy ──
            try:
                gold_result = _get_gold_signal()
                if gold_result and gold_result["signal"] != "NO_TRADE":
                    score = rm.score_signal(config.SYMBOL_GOLD, gold_result)
                    try:
                        import trade_memory as tm
                        score += tm.get_adaptive_score(config.SYMBOL_GOLD, gold_result.get("comment",""))
                    except Exception: pass
                    candidates.append((score, config.SYMBOL_GOLD, gold_result, True))
                    log_event("INFO", f"[{config.SYMBOL_GOLD}] Candidate score:{score:.1f}")
            except Exception as e:
                log_event("ERROR", f"[GOLD] Signal error: {e}")

            # ── AMD Standalone ──
            try:
                amd_result = _get_amd_signal(config.SYMBOL_GOLD)
                if amd_result and amd_result["signal"] != "NO_TRADE":
                    score = rm.score_signal(config.SYMBOL_GOLD, amd_result)
                    try:
                        import trade_memory as tm
                        score += tm.get_adaptive_score(config.SYMBOL_GOLD, amd_result.get("comment",""))
                    except Exception: pass
                    candidates.append((score, config.SYMBOL_GOLD, amd_result, True))
                    log_event("INFO", f"[{config.SYMBOL_GOLD}] AMD Candidate score:{score:.1f}")
            except Exception as e:
                log_event("ERROR", f"[GOLD-AMD] Signal error: {e}")

            # ── Silver Bullet Standalone ──
            try:
                sb_result = _get_silver_bullet_signal(config.SYMBOL_GOLD)
                if sb_result and sb_result["signal"] != "NO_TRADE":
                    score = rm.score_signal(config.SYMBOL_GOLD, sb_result)
                    try:
                        import trade_memory as tm
                        score += tm.get_adaptive_score(config.SYMBOL_GOLD, sb_result.get("comment",""))
                    except Exception: pass
                    candidates.append((score, config.SYMBOL_GOLD, sb_result, True))
                    log_event("INFO", f"[{config.SYMBOL_GOLD}] SB Candidate score:{score:.1f}")
            except Exception as e:
                log_event("ERROR", f"[GOLD-SB] Signal error: {e}")

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                log_event("INFO", f"Total candidates: {len(candidates)} — Best score: {candidates[0][0]:.1f}")
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
        _finalize_sl_tp(sym, result, entry)
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _get_amd_signal(sym: str) -> dict:
    price = mt5c.get_price(sym)
    if price is None:
        return None
    if not rm.can_open_trade(sym):
        return None

    point  = mt5c.get_symbol_point(sym)
    df_m15 = mt5c.get_candles(config.TIMEFRAME_M15, config.CANDLE_M15, sym)
    if df_m15 is None:
        return None

    result = strategy_amd.generate_amd_signal(sym, df_m15, point)

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp(sym, result, entry)
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _get_silver_bullet_signal(sym: str) -> dict:
    if not strategy_silver_bullet.is_silver_bullet_window():
        return None

    price = mt5c.get_price(sym)
    if price is None:
        return None
    if not rm.can_open_trade(sym):
        return None

    point = mt5c.get_symbol_point(sym)
    df_m5 = mt5c.get_candles(config.TIMEFRAME_M5, config.CANDLE_M5, sym)
    if df_m5 is None:
        return None

    result = strategy_silver_bullet.generate_silver_bullet_signal(sym, df_m5, point)

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        _finalize_sl_tp(sym, result, entry)
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _execute_candidates(candidates: list):
    for score, symbol, result, is_gold in candidates:

        if rm.is_daily_loss_limit_hit():
            log_event("WARNING", "Daily limit — stopping execution.")
            break

        if not rm.can_open_trade(symbol):
            continue

        try:
            import trade_memory as tm
            if tm.is_pattern_blocked(symbol, result.get("comment","")):
                continue
        except Exception:
            pass

        lot = result.get("lot", config.LOT_SIZE_GOLD)
        sig = result["signal"]
        tp  = result.get("tp3") or result.get("tp1")

        if sig == "BUY":
            log_event("INFO", f"[{symbol}] BUY Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} Score:{score:.1f}")
            order = mt5c.open_buy_order(symbol=symbol, sl_price=result["sl"],
                                        tp_price=tp, lot=lot, comment=result["comment"])
            if order:
                log_event("INFO", f"[{symbol}] BUY OK Ticket:{order.order}")
            else:
                log_event("ERROR", f"[{symbol}] BUY fail.")

        elif sig == "SELL":
            log_event("INFO", f"[{symbol}] SELL Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} Score:{score:.1f}")
            order = mt5c.open_sell_order(symbol=symbol, sl_price=result["sl"],
                                         tp_price=tp, lot=lot, comment=result["comment"])
            if order:
                log_event("INFO", f"[{symbol}] SELL OK Ticket:{order.order}")
            else:
                log_event("ERROR", f"[{symbol}] SELL fail.")


if __name__ == "__main__":
    run()
