# ============================================================
#  trade_manager.py — V8.4
#  Partial close (1:1, 70%), BE, SL trail, weekend close,
#  SL/TP hit detection feeding trade_memory
# ============================================================

import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import config
from logger import log_event, log_trade

_prev_positions = {}
_partial_done   = set()
_orig_risk      = {}   # ticket -> original SL distance (R basis, trail se pehle)
_max_fav        = {}   # ticket -> max favorable excursion (R) — progressive trail


def manage_open_trades():
    global _prev_positions, _partial_done

    try:
        from risk import risk_manager as rm
        current_pos = mt5.positions_get() or []
        current_tix = {p.ticket for p in current_pos}

        for ticket, info in list(_prev_positions.items()):
            if ticket not in current_tix:
                _check_sl_hit(ticket, info["symbol"], rm)
                _partial_done.discard(ticket)
                _orig_risk.pop(ticket, None)
                _max_fav.pop(ticket, None)

        _prev_positions = {
            p.ticket: {"symbol":p.symbol,"entry":p.price_open,"type":p.type}
            for p in current_pos
        }
    except Exception as e:
        log_event("WARNING", f"SL tracking error: {e}")

    all_symbols = [config.SYMBOL_GOLD] + config.SYMBOL_ICT
    for symbol in all_symbols:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            continue
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
        if not deals:
            return
        for deal in deals:
            if deal.position_id == ticket and deal.entry == 1:
                comment = deal.comment or ""
                if deal.profit < 0:
                    log_event("INFO", f"[{symbol}] SL hit (ticket:{ticket} P&L:{deal.profit:.2f})")
                    rm.record_sl_hit(symbol)
                    rm.record_trade_result(symbol, deal.profit, was_sl=True)
                    try:
                        from memory import trade_memory as tm
                        tm.record_result(symbol, comment, deal.profit, was_sl=True)
                    except Exception as e:
                        log_event("WARNING", f"Trade memory error: {e}")
                else:
                    log_event("INFO", f"[{symbol}] TP/Close (ticket:{ticket} P&L:{deal.profit:.2f})")
                    rm.record_trade_result(symbol, deal.profit, was_sl=False)
                    try:
                        from memory import trade_memory as tm
                        tm.record_result(symbol, comment, deal.profit, was_sl=False)
                    except Exception as e:
                        log_event("WARNING", f"Trade memory error: {e}")
                break
    except Exception as e:
        log_event("WARNING", f"SL check [{symbol}]: {e}")


def _manage_trade(pos):
    entry   = pos.price_open
    current = pos.price_current
    sl      = pos.sl
    tp      = pos.tp
    ticket  = pos.ticket
    symbol  = pos.symbol
    is_buy  = pos.type == mt5.ORDER_TYPE_BUY

    # Original risk (trail se pehle) yaad rakho — R calculation ke liye.
    # Pehli baar position dikhe to uski SL distance store kar lo.
    if ticket not in _orig_risk:
        r0 = (entry - sl) if is_buy else (sl - entry)
        if r0 > 0:
            _orig_risk[ticket] = r0
    orig_risk = _orig_risk.get(ticket, 0)

    # ── Smart time-based exit (scalp): max hold cross → close, LEKIN
    #    sirf tab jab trade abhi solid profit (>TIME_STOP_MAX_PROFIT_R)
    #    mein na ho. Winners chalte rahein (BE/trail se protected),
    #    sirf stuck/losing trades katein. Backtest: yeh edge behtar
    #    karta hai (+8.41R→+9.43R) aur winners ko jaldi nahi kaatta.
    max_hold = getattr(config, "MAX_HOLD_MINUTES", 0)
    if max_hold and pos.time and orig_risk > 0:
        age_min = (datetime.now(timezone.utc).timestamp() - pos.time) / 60.0
        if age_min >= max_hold:
            cur_profit_pts = (current - entry) if is_buy else (entry - current)
            cur_r = cur_profit_pts / orig_risk
            tsp = getattr(config, "TIME_STOP_MAX_PROFIT_R", None)
            if tsp is None or cur_r <= tsp:
                log_event("INFO",
                    f"[{symbol}][{ticket}] Max hold {max_hold}min (age "
                    f"{age_min:.0f}min, {cur_r:+.2f}R) — force close. "
                    f"P&L:{pos.profit:.2f}")
                _close_position(pos)
                return
            # else: profit >tsp — winner chalne do, close nahi karte

    sl_size = (entry - sl) if is_buy else (sl - entry)
    if sl_size <= 0: return

    profit_pts = (current - entry) if is_buy else (entry - current)

    if getattr(config, "PARTIAL_CLOSE_ENABLED", True):
        partial_trigger = sl_size * config.PARTIAL_CLOSE_RR
        if ticket not in _partial_done and profit_pts >= partial_trigger:
            _do_partial_close(pos, symbol, ticket)
            _partial_done.add(ticket)
            return

    info = mt5.symbol_info(symbol)
    digits = info.digits if info else 5

    cur_r = profit_pts / orig_risk if orig_risk > 0 else 0
    _max_fav[ticket] = max(_max_fav.get(ticket, 0.0), cur_r)
    max_fav = _max_fav[ticket]

    new_sl = None
    trail_mode = getattr(config, "TRAIL_MODE", None)

    if trail_mode == "giveback" and orig_risk > 0:
        # ── Progressive trend-rider trail: peak favorable se GIVEBACK_R
        #    neeche SL trail (activate hone ke baad). Bara trend ride hota
        #    hai. Backtest (6mo): full +22R→+39R, bade winners capture.
        act  = getattr(config, "TRAIL_ACTIVATE_R", 3.0)
        give = getattr(config, "TRAIL_GIVEBACK_R", 1.5)
        if max_fav >= act:
            lvl_r  = max(max_fav - give, 0.0)
            cand   = round(entry + lvl_r * orig_risk if is_buy
                           else entry - lvl_r * orig_risk, digits)
            if (is_buy and cand > sl) or (not is_buy and cand < sl):
                new_sl = cand
                log_event("INFO",
                    f"[{symbol}][{ticket}] TRAIL peak{max_fav:.1f}R → "
                    f"SL {new_sl} (lock {lvl_r:.1f}R)")
        elif max_fav >= 1.0:
            be = round(entry, digits)
            if (is_buy and sl < be) or (not is_buy and sl > be):
                new_sl = be
                log_event("INFO", f"[{symbol}][{ticket}] 1:1 — BE {new_sl}")
    else:
        # ── Legacy fixed scalp trail (2R → lock 1R, 1R → BE) ──
        if profit_pts >= sl_size * 2.0:
            tp1_level = round(entry + sl_size if is_buy else entry - sl_size, digits)
            if (is_buy and sl < tp1_level) or (not is_buy and sl > tp1_level):
                new_sl = tp1_level
                log_event("INFO", f"[{symbol}][{ticket}] 1:2 — SL→TP1 {new_sl}")
        elif profit_pts >= sl_size:
            be = round(entry, digits)
            if (is_buy and sl < be) or (not is_buy and sl > be):
                new_sl = be
                log_event("INFO", f"[{symbol}][{ticket}] 1:1 — BE {new_sl}")

    if new_sl is not None:
        _move_sl(ticket, new_sl, tp)


def _do_partial_close(pos, symbol, ticket):
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return

    close_pct  = config.PARTIAL_CLOSE_PCT
    step       = info.volume_step or 0.01
    close_vol  = round(round((pos.volume * close_pct) / step) * step, 2)
    remain_vol = round(pos.volume - close_vol, 2)

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
        "action": mt5.TRADE_ACTION_DEAL,
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
