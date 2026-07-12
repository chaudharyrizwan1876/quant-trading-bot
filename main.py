# ============================================================
#  main.py — GoldBot V7.2
#  FIX: Correlation check ab direction-aware — execute se
#  pehle hota hai jab signal ka BUY/SELL pata chal jata hai
# ============================================================

import time
import config
import mt5_connector as mt5c
import strategy_gold
import strategy_ict
import news_reader
import strategy_amd
import trade_manager
import risk_manager as rm
from logger import log_event


def run():
    log_event("INFO", "========== GoldBot V7.2 Starting ==========")

    if not mt5c.connect():
        log_event("ERROR", "MT5 connection fail.")
        return

    log_event("INFO", f"Gold : {config.SYMBOL_GOLD}")
    log_event("INFO", f"Forex: {', '.join(config.SYMBOL_ICT)}")
    log_event("INFO", f"Risk : {config.RISK_PERCENT*100:.0f}% per trade (EQUITY)")
    log_event("INFO", f"TP   : 1:{config.RR_FINAL:.0f} | Partial: {config.PARTIAL_CLOSE_PCT*100:.0f}% at 1:{config.PARTIAL_CLOSE_RR}")

    if config.NEWS_ENABLED:
        news_reader.print_todays_news()

    try:
        while True:

            if rm.is_daily_loss_limit_hit():
                log_event("WARNING", "Daily loss limit hit — All trading paused.")
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

            try:
                gold_result = _get_gold_signal()
                if gold_result and gold_result["signal"] != "NO_TRADE":
                    score = rm.score_signal(config.SYMBOL_GOLD, gold_result)
                    candidates.append((score, config.SYMBOL_GOLD, gold_result, True))
                    log_event("INFO", f"[{config.SYMBOL_GOLD}] Candidate score:{score:.1f}")
            except Exception as e:
                log_event("ERROR", f"[GOLD] Signal error: {e}")

            # AMD standalone — Gold ke liye alag se check
            try:
                amd_result = _get_amd_signal(config.SYMBOL_GOLD)
                if amd_result and amd_result["signal"] != "NO_TRADE":
                    score = rm.score_signal(config.SYMBOL_GOLD, amd_result)
                    candidates.append((score, config.SYMBOL_GOLD, amd_result, True))
                    log_event("INFO", f"[{config.SYMBOL_GOLD}] AMD Candidate score:{score:.1f}")
            except Exception as e:
                log_event("ERROR", f"[GOLD-AMD] Signal error: {e}")

            for sym in config.SYMBOL_ICT:
                try:
                    fx_result = _get_forex_signal(sym)
                    if fx_result and fx_result["signal"] != "NO_TRADE":
                        score = rm.score_signal(sym, fx_result)
                        candidates.append((score, sym, fx_result, False))
                        log_event("INFO", f"[{sym}] Candidate score:{score:.1f}")
                except Exception as e:
                    log_event("ERROR", f"[{sym}] Signal error: {e}")

                # AMD standalone — is pair ke liye bhi alag se check
                try:
                    amd_result = _get_amd_signal(sym)
                    if amd_result and amd_result["signal"] != "NO_TRADE":
                        score = rm.score_signal(sym, amd_result)
                        candidates.append((score, sym, amd_result, False))
                        log_event("INFO", f"[{sym}] AMD Candidate score:{score:.1f}")
                except Exception as e:
                    log_event("ERROR", f"[{sym}-AMD] Signal error: {e}")

            if candidates:
                candidates.sort(key=lambda x: x[0], reverse=True)
                log_event("INFO", f"Total candidates: {len(candidates)} — Best: {candidates[0][1]} ({candidates[0][0]:.1f})")
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

    # Direction abhi pata nahi — sirf basic checks (open/spread/blocked)
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
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _get_amd_signal(sym: str) -> dict:
    """
    Standalone AMD (Accumulation-Manipulation-Distribution) signal.
    Gold aur Forex dono ke liye — Gold/ICT strategy se bilkul
    ALAG chalti hai. Sirf M15 candles pe based hai.
    """
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
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _get_forex_signal(sym: str) -> dict:
    price = mt5c.get_price(sym)
    if price is None: return None
    print(f"{sym} — Bid:{price['bid']:.5f}  Ask:{price['ask']:.5f}")

    if not rm.can_open_trade(sym):
        return None

    point  = mt5c.get_symbol_point(sym)
    result = None

    if config.NEWS_ENABLED and config.NEWS_TRADE_ENABLED:
        news_sig = news_reader.get_news_signal(sym)
        if news_sig["signal"] != "NO_TRADE":
            sl_size = config.NEWS_SL_PIPS_FOREX * point * 10
            result  = _build_news_trade(sym, news_sig["signal"], price, sl_size, config.RR_FINAL)

    if result is None or result["signal"] == "NO_TRADE":
        df_h1  = mt5c.get_candles(config.TIMEFRAME_H1,  config.CANDLE_H1,  sym)
        df_m15 = mt5c.get_candles(config.TIMEFRAME_M15, config.CANDLE_M15, sym)
        df_m5  = mt5c.get_candles(config.TIMEFRAME_M5,  config.CANDLE_M5,  sym)
        df_m1  = mt5c.get_candles(config.TIMEFRAME_M1,  config.CANDLE_M1,  sym)

        if any(df is None for df in [df_m15, df_m5, df_m1]):
            log_event("WARNING", f"[{sym}] Candles nahi milin.")
            return None

        result = strategy_ict.generate_ict_signal(
            symbol=sym, df_m15=df_m15, df_m5=df_m5,
            df_m1=df_m1, point=point, df_h1=df_h1
        )

    if result and result["signal"] != "NO_TRADE":
        entry = result.get("entry") or price["ask"]
        result["lot"] = rm.calculate_lot(sym, result["sl"], entry)

    return result


def _execute_candidates(candidates: list):
    for score, symbol, result, is_gold in candidates:

        if rm.is_daily_loss_limit_hit():
            log_event("WARNING", "Daily limit — stopping execution.")
            break

        sig = result["signal"]

        # Basic checks dobara (open positions state badal sakti hai)
        if not rm.can_open_trade(symbol):
            continue

        # FIX: Ab direction pata hai — correlation direction-check yahan
        if not is_gold and rm.is_correlated_conflict(symbol, sig):
            continue

        try:
            import trade_memory as tm
            if tm.is_pattern_blocked(result.get("comment","")):
                continue
        except Exception:
            pass

        lot = result.get("lot", config.LOT_SIZE_GOLD if is_gold else config.LOT_SIZE_ICT)
        tp  = result.get("tp3") or result.get("tp1")

        if sig == "BUY":
            log_event("INFO", f"[{symbol}] BUY Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} Score:{score:.1f}")
            order = mt5c.open_buy_order(symbol=symbol, sl_price=result["sl"],
                                        tp_price=tp, lot=lot, comment=result["comment"])
            if order:
                log_event("INFO", f"[{symbol}] BUY OK Ticket:{order.order}")
                if "zone" in result:
                    strategy_ict.set_re_entry_state(symbol, "BULLISH", result["zone"])
            else:
                log_event("ERROR", f"[{symbol}] BUY fail.")

        elif sig == "SELL":
            log_event("INFO", f"[{symbol}] SELL Lot:{lot} SL:{result['sl']:.5f} TP:{tp:.5f} Score:{score:.1f}")
            order = mt5c.open_sell_order(symbol=symbol, sl_price=result["sl"],
                                         tp_price=tp, lot=lot, comment=result["comment"])
            if order:
                log_event("INFO", f"[{symbol}] SELL OK Ticket:{order.order}")
                if "zone" in result:
                    strategy_ict.set_re_entry_state(symbol, "BEARISH", result["zone"])
            else:
                log_event("ERROR", f"[{symbol}] SELL fail.")


def _build_news_trade(symbol, direction, price, sl_size, tp_rr) -> dict:
    if direction == "BUY":
        entry = price["ask"]; sl = entry - sl_size
        tp1 = entry + sl_size*1.5; tp3 = entry + sl_size*tp_rr
    else:
        entry = price["bid"]; sl = entry + sl_size
        tp1 = entry - sl_size*1.5; tp3 = entry - sl_size*tp_rr
    return {"signal":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp1,
            "tp3":tp3,"comment":f"NEWS_{direction}_{symbol}"}


if __name__ == "__main__":
    run()
