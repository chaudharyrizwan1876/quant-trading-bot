# ============================================================
#  trade_manager.py — V7.0
#  NEW: Partial Close at 1:1.5 → 70% close, 30% trails
#  Trail: 1:1 BE → 1:2 SL to TP1 level → 1:3 final close
# ============================================================

import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import config
from logger import log_event, log_trade

_prev_positions = {}
_partial_done   = set()   # tickets jinka partial close ho chuka


def manage_open_trades():
    global _prev_positions, _partial_done

    try:
        import risk_manager as rm
        current_pos = mt5.positions_get() or []
        current_tix = {p.ticket for p in current_pos}

        for ticket, info in list(_prev_positions.items()):
            if ticket not in current_tix:
                _check_sl_hit(ticket, info["symbol"], rm)
                _partial_done.discard(ticket)

        _prev_positions = {
            p.ticket: {"symbol":p.symbol,"entry":p.price_open,"type":p.type}
            for p in current_pos
        }
    except Exception as e:
        log_event("WARNING", f"SL tracking error: {e}")

    all_symbols = [config.SYMBOL_GOLD] + config.SYMBOL_ICT
    for symbol in all_symbols:
        positions = mt5.positions_get(symbol=symbol)
        if not positions: continue
        for pos in positions:
            try:
                _manage_trade(pos)
            except Exception as e:
                log_event("ERROR", f"Trade manage [{symbol}]: {e}")

    _weekend_close_gold()


def _check_sl_hit(ticket, symbol, rm):
    try:
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(minutes=15), now)
        if not deals: return
        for deal in deals:
            if deal.position_id == ticket and deal.entry == 1:
                comment = deal.comment or ""
                if deal.profit < 0:
                    log_event("INFO", f"[{symbol}] SL hit (ticket:{ticket} P&L:{deal.profit:.2f})")
                    rm.record_sl_hit(symbol)
                    try:
                        import trade_memory as tm
                        tm.record_result(symbol, comment, deal.profit, was_sl=True)
                    except Exception as e:
                        log_event("WARNING", f"Trade memory error: {e}")
                    try:
                        import strategy_ict as ict
                        ict.clear_re_entry_state(symbol)
                    except Exception: pass
                else:
                    log_event("INFO", f"[{symbol}] TP/Close (ticket:{ticket} P&L:{deal.profit:.2f})")
                    try:
                        import trade_memory as tm
                        tm.record_result(symbol, comment, deal.profit, was_sl=False)
                    except Exception as e:
                        log_event("WARNING", f"Trade memory error: {e}")
                    try:
                        import strategy_ict as ict
                        ict.clear_re_entry_state(symbol)
                    except Exception: pass
                break
    except Exception as e:
        log_event("WARNING", f"SL check [{symbol}]: {e}")


# ─────────────────────────────────────────────
#  UNIFIED TRADE MANAGEMENT — Gold + Forex
#  1. Partial close at 1:1.5 → 70%
#  2. BE at 1:1 (on remaining 30%)
#  3. SL trail to TP1 level at 1:2
#  4. Final close at 1:3 (broker TP already set)
# ─────────────────────────────────────────────

def _manage_trade(pos):
    entry   = pos.price_open
    current = pos.price_current
    sl      = pos.sl
    tp      = pos.tp
    ticket  = pos.ticket
    symbol  = pos.symbol
    is_buy  = pos.type == mt5.ORDER_TYPE_BUY

    sl_size = (entry - sl) if is_buy else (sl - entry)
    if sl_size <= 0: return

    profit_pts = (current - entry) if is_buy else (entry - current)

    # ── STEP 1: Partial Close at 1:1.5 ──
    partial_trigger = sl_size * config.PARTIAL_CLOSE_RR
    if ticket not in _partial_done and profit_pts >= partial_trigger:
        _do_partial_close(pos, symbol, ticket)
        _partial_done.add(ticket)
        return   # is loop mein aage trail skip karo — next loop mein hoga

    # ── STEP 2 & 3: BE / Trail (remaining position pe) ──
    digits = 5
    info = mt5.symbol_info(symbol)
    if info: digits = info.digits

    new_sl = None
    if profit_pts >= sl_size * 2.0:
        tp1_level = round(entry + sl_size if is_buy else entry - sl_size, digits)
        if (is_buy and sl < tp1_level) or (not is_buy and sl > tp1_level):
            new_sl = tp1_level
            log_event("INFO", f"[{symbol}][{ticket}] 1:2 — SL→TP1 {new_sl}")
    elif profit_pts >= sl_size:
        be_buf = config.GOLD_SL_BUFFER if "XAU" in symbol.upper() else \
                 config.BE_BUFFER_POINTS * (info.point if info else 0.0001) * 10
        be = round(entry + be_buf if is_buy else entry - be_buf, digits) \
             if "XAU" in symbol.upper() else \
             round(entry + be_buf if is_buy else entry - be_buf, digits)
        if "XAU" in symbol.upper():
            be = round(entry, digits)
        if (is_buy and sl < be) or (not is_buy and sl > be):
            new_sl = be
            log_event("INFO", f"[{symbol}][{ticket}] 1:1 — BE {new_sl}")

    if new_sl is not None:
        _move_sl(ticket, new_sl, tp)


def _do_partial_close(pos, symbol, ticket):
    """Position ka 70% close karo, 30% chalta rahe."""
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return

    close_pct   = config.PARTIAL_CLOSE_PCT
    step        = info.volume_step or 0.01
    close_vol   = round(round((pos.volume * close_pct) / step) * step, 2)
    remain_vol  = round(pos.volume - close_vol, 2)

    # Agar remaining ya close volume broker minimum se kam ho to skip
    if close_vol < info.volume_min or remain_vol < info.volume_min:
        log_event("INFO",
            f"[{symbol}][{ticket}] Partial close skip — "
            f"volume too small (close:{close_vol} remain:{remain_vol})"
        )
        return

    if pos.type == mt5.ORDER_TYPE_BUY:
        price, order_type = tick.bid, mt5.ORDER_TYPE_SELL
    else:
        price, order_type = tick.ask, mt5.ORDER_TYPE_BUY

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "position":     ticket,
        "symbol":       symbol,
        "volume":       close_vol,
        "type":         order_type,
        "price":        price,
        "deviation":    20,
        "magic":        123456,
        "comment":      "PartialClose",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log_event("INFO",
            f"[{symbol}][{ticket}] PARTIAL CLOSE 70% OK — "
            f"Closed:{close_vol} Remaining:{remain_vol}"
        )
    else:
        log_event("ERROR",
            f"[{symbol}][{ticket}] Partial close fail: "
            f"{result.retcode if result else 'None'}"
        )


# ─────────────────────────────────────────────
#  WEEKEND CLOSE
# ─────────────────────────────────────────────

def _weekend_close_gold():
    now = datetime.now(timezone.utc)
    if not (now.weekday()==4 and now.hour>=20 and now.minute>=30):
        return
    positions = mt5.positions_get(symbol=config.SYMBOL_GOLD)
    if not positions: return
    for pos in positions:
        log_event("INFO", f"GOLD [{pos.ticket}] Weekend close P&L:{pos.profit:.2f}")
        _close_position(pos)


def _close_position(pos):
    tick = mt5.symbol_info_tick(pos.symbol)
    if not tick: return
    if pos.type == mt5.ORDER_TYPE_BUY:
        price, order_type = tick.bid, mt5.ORDER_TYPE_SELL
    else:
        price, order_type = tick.ask, mt5.ORDER_TYPE_BUY
    req = {
        "action":"TRADE_ACTION_DEAL" if False else mt5.TRADE_ACTION_DEAL,
        "position": pos.ticket, "symbol": pos.symbol, "volume": pos.volume,
        "type": order_type, "price": price, "deviation": 20, "magic": 123456,
        "comment": "WeekendClose", "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(req)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log_event("INFO", f"[{pos.symbol}] Weekend closed OK")
    else:
        log_event("ERROR", f"[{pos.symbol}] Weekend close fail")


def _move_sl(ticket, new_sl, tp):
    req = {"action":mt5.TRADE_ACTION_SLTP,"position":ticket,"sl":new_sl,"tp":tp}
    result = mt5.order_send(req)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log_event("INFO", f"SL moved [{ticket}] → {new_sl}")
        log_trade("SL_TRAIL", 0, new_sl, tp, 0, comment=f"ticket_{ticket}")
    else:
        log_event("WARNING", f"SL move fail [{ticket}]")
