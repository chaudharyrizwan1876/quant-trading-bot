# ============================================================
#  mt5_connector.py — MT5 Connection + Orders V8.4
# ============================================================

import re
import MetaTrader5 as mt5
import pandas as pd
import config
from logger import log_event

TIMEFRAME_MAP = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def _clean_comment(comment: str) -> str:
    if not comment:
        return "GoldBot"
    clean = re.sub(r'[^A-Za-z0-9_]', '', str(comment))
    return clean[:24] if clean else "GoldBot"


def connect():
    if not mt5.initialize():
        log_event("ERROR", f"MT5 initialize fail: {mt5.last_error()}")
        return False
    authorized = mt5.login(
        login    = config.MT5_LOGIN,
        password = config.MT5_PASSWORD,
        server   = config.MT5_SERVER
    )
    if not authorized:
        log_event("ERROR", f"MT5 login fail: {mt5.last_error()}")
        mt5.shutdown()
        return False
    log_event("INFO", f"MT5 connected — Account: {config.MT5_LOGIN}")
    return True


def disconnect():
    mt5.shutdown()
    log_event("INFO", "MT5 disconnected.")


def get_price(symbol: str):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log_event("ERROR", f"Price fail [{symbol}]: {mt5.last_error()}")
        return None
    return {"bid": tick.bid, "ask": tick.ask}


def get_candles(timeframe_str: str, count: int, symbol: str):
    tf    = TIMEFRAME_MAP.get(timeframe_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        log_event("ERROR",
            f"Candles fail [{symbol} {timeframe_str}]: {mt5.last_error()}"
        )
        return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    return df


def get_symbol_point(symbol: str):
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0001
    return info.point


def get_min_stop_distance(symbol: str) -> float:
    """Broker ka minimum SL/TP distance (price units), 1.5x safety margin ke saath."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    point       = info.point
    stops_level = max(info.trade_stops_level, 1) * point
    return stops_level * 1.5


def get_tick_value_info(symbol: str) -> dict:
    """Risk_manager ke liye — lot/SL calculation mein use hota hai."""
    info = mt5.symbol_info(symbol)
    if info is None:
        return None
    return {
        "tick_value": info.trade_tick_value,
        "tick_size":  info.trade_tick_size,
        "point":      info.point,
        "min_lot":    info.volume_min,
        "max_lot":    info.volume_max,
        "lot_step":   info.volume_step or 0.01,
        "digits":     info.digits,
    }


def _enforce_stop_level(symbol: str, price: float, sl: float, tp: float, is_buy: bool):
    info = mt5.symbol_info(symbol)
    if info is None:
        return sl, tp
    safety = get_min_stop_distance(symbol)
    if is_buy:
        if (price - sl) < safety: sl = price - safety
        if (tp - price) < safety: tp = price + safety
    else:
        if (sl - price) < safety: sl = price + safety
        if (price - tp) < safety: tp = price - safety
    digits = info.digits
    return round(sl, digits), round(tp, digits)


def _normalize_lot(symbol: str, lot: float) -> float:
    info = mt5.symbol_info(symbol)
    if info is None:
        return round(lot, 2)
    min_lot, max_lot = info.volume_min, info.volume_max
    step = info.volume_step or 0.01
    steps = round(lot / step)
    fixed = round(steps * step, 2)
    return max(min_lot, min(fixed, max_lot))


def _filling_modes(symbol: str) -> list:
    """
    Broker jo filling mode support karta hai usse shuru karo,
    phir fallback order: IOC → FOK → RETURN. Galat filling mode
    ('Unsupported filling mode' / retcode 10030) pe next try.
    """
    info = mt5.symbol_info(symbol)
    preferred = []
    try:
        fm = info.filling_mode if info else 0
        # filling_mode ek bitmask hai: 1=FOK, 2=IOC (broker-dependent)
        if fm & 2:
            preferred.append(mt5.ORDER_FILLING_IOC)
        if fm & 1:
            preferred.append(mt5.ORDER_FILLING_FOK)
    except Exception:
        pass
    # Ensure all three present as fallbacks, dedup preserve order
    for mode in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        if mode not in preferred:
            preferred.append(mode)
    return preferred


_RETRY_RETCODES = None


def _retry_retcodes():
    global _RETRY_RETCODES
    if _RETRY_RETCODES is None:
        _RETRY_RETCODES = {
            getattr(mt5, "TRADE_RETCODE_REQUOTE", 10004),
            getattr(mt5, "TRADE_RETCODE_PRICE_CHANGED", 10020),
            getattr(mt5, "TRADE_RETCODE_PRICE_OFF", 10021),
        }
    return _RETRY_RETCODES


def _send_deal(symbol, order_type, is_buy, sl_price, tp_price, lot, comment,
               max_retries=2):
    """
    Robust order sender: filling-mode fallback + requote/price-change
    retry (fresh price har retry pe). Return: successful result ya None.
    """
    lot     = _normalize_lot(symbol, lot or config.LOT_SIZE_GOLD)
    comment = _clean_comment(comment)
    side    = "BUY" if is_buy else "SELL"
    fill_modes = _filling_modes(symbol)

    for fill in fill_modes:
        for attempt in range(max_retries + 1):
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                log_event("ERROR", f"{side} fail [{symbol}] — price nahi mili.")
                return None
            price = tick.ask if is_buy else tick.bid
            sl, tp = _enforce_stop_level(symbol, price, sl_price, tp_price, is_buy)

            req = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       float(lot),
                "type":         order_type,
                "price":        price,
                "sl":           round(float(sl), 5),
                "tp":           round(float(tp), 5),
                "deviation":    20,
                "magic":        123456,
                "comment":      comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": fill,
            }

            log_event("INFO",
                f"{side} request [{symbol}] Lot:{lot} Px:{price:.5f} "
                f"SL:{sl:.5f} TP:{tp:.5f} fill:{fill} attempt:{attempt} Comment:{comment}")

            result = mt5.order_send(req)
            if result is None:
                log_event("ERROR", f"{side} fail [{symbol}] — order_send None: {mt5.last_error()}")
                return None

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                log_event("INFO",
                    f"{side} OK [{symbol}] Ticket:{result.order} SL:{sl:.5f} TP:{tp:.5f}")
                return result

            # Requote / price moved → refetch & retry
            if result.retcode in _retry_retcodes():
                log_event("WARNING",
                    f"{side} [{symbol}] retcode:{result.retcode} ({result.comment}) — retrying.")
                continue

            # Invalid/unsupported filling → break to next filling mode
            if result.retcode == getattr(mt5, "TRADE_RETCODE_INVALID_FILL", 10030):
                log_event("WARNING",
                    f"{side} [{symbol}] filling {fill} unsupported — trying next mode.")
                break

            # Any other error — don't hammer the broker
            log_event("ERROR",
                f"{side} fail [{symbol}] retcode:{result.retcode} | {result.comment}")
            return None

    log_event("ERROR", f"{side} fail [{symbol}] — all filling modes/retries exhausted.")
    return None


def open_buy_order(symbol: str, sl_price: float, tp_price: float,
                   lot=None, comment="GoldBot_BUY"):
    return _send_deal(symbol, mt5.ORDER_TYPE_BUY, True,
                      sl_price, tp_price, lot, comment)


def open_sell_order(symbol: str, sl_price: float, tp_price: float,
                    lot=None, comment="GoldBot_SELL"):
    return _send_deal(symbol, mt5.ORDER_TYPE_SELL, False,
                      sl_price, tp_price, lot, comment)


def get_open_positions(symbol: str = None):
    if symbol:
        pos = mt5.positions_get(symbol=symbol)
    else:
        pos = mt5.positions_get()
    return list(pos) if pos else []
