# ============================================================
#  mt5_connector.py — MT5 Connection + Orders (Multi-Symbol)
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
    """
    MT5 comment requirements:
    - Max 31 chars (kuch brokers ke liye safe limit 24 rakha hai)
    - Only ASCII alphanumeric + underscore
    - No spaces, no special chars
    """
    if not comment:
        return "GoldBot"
    clean = re.sub(r'[^A-Za-z0-9_]', '', str(comment))
    return clean[:24] if clean else "GoldBot"


# ── Connection ──

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


# ── Market Data ──

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


def _normalize_lot(symbol: str, lot: float) -> float:
    """
    Lot size ko broker ke min/max/step ke hisaab se theek karo.
    Galat lot (jaise 1.53 jab step 0.01 ho, ya max se zyada) order
    reject karwa sakta hai — "Invalid" errors aksar isi wajah se aate hain.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return round(lot, 2)

    min_lot  = info.volume_min
    max_lot  = info.volume_max
    step     = info.volume_step or 0.01

    # Step ke multiple pe round karo
    steps = round(lot / step)
    fixed = round(steps * step, 2)

    fixed = max(min_lot, min(fixed, max_lot))
    return fixed


def _enforce_stop_level(symbol: str, price: float, sl: float, tp: float,
                        is_buy: bool):
    """
    Broker ka minimum stop-level distance check karo.
    Agar SL/TP us se paas hain to door kar do — warna
    'Invalid stops' (retcode 10016) error aayega.
    """
    info = mt5.symbol_info(symbol)
    if info is None:
        return sl, tp

    point       = info.point
    stops_level = max(info.trade_stops_level, 1) * point  # broker minimum
    safety      = stops_level * 1.5  # thoda extra margin

    if is_buy:
        if (price - sl) < safety:
            sl = price - safety
        if (tp - price) < safety:
            tp = price + safety
    else:
        if (sl - price) < safety:
            sl = price + safety
        if (price - tp) < safety:
            tp = price - safety

    digits = info.digits
    return round(sl, digits), round(tp, digits)


# ── Orders ──

def open_buy_order(symbol: str, sl_price: float, tp_price: float,
                   lot=None, comment="GoldBot_BUY"):
    lot     = lot or config.LOT_SIZE_GOLD
    lot     = _normalize_lot(symbol, lot)
    comment = _clean_comment(comment)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log_event("ERROR", f"BUY fail [{symbol}] — price nahi mili.")
        return None

    ask = tick.ask
    sl_price, tp_price = _enforce_stop_level(
        symbol, ask, sl_price, tp_price, is_buy=True
    )

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       float(lot),
        "type":         mt5.ORDER_TYPE_BUY,
        "price":        ask,
        "sl":           round(float(sl_price), 5),
        "tp":           round(float(tp_price), 5),
        "deviation":    20,
        "magic":        123456,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    log_event("INFO",
        f"BUY request [{symbol}] "
        f"Lot:{lot} Ask:{ask:.5f} "
        f"SL:{sl_price:.5f} TP:{tp_price:.5f} "
        f"Comment:{comment} (len={len(comment)})"
    )

    check = mt5.order_check(req)
    if check is not None and check.retcode != mt5.TRADE_RETCODE_DONE \
            and check.retcode != 0:
        log_event("WARNING",
            f"BUY pre-check [{symbol}] retcode:{check.retcode} "
            f"comment:{check.comment}"
        )

    result = mt5.order_send(req)

    if result is None:
        log_event("ERROR",
            f"BUY fail [{symbol}] — order_send None: {mt5.last_error()}"
        )
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_event("ERROR",
            f"BUY fail [{symbol}] retcode:{result.retcode} | {result.comment}"
        )
        return None

    log_event("INFO",
        f"BUY OK [{symbol}] Ticket:{result.order} "
        f"Ask:{ask:.5f} SL:{sl_price:.5f} TP:{tp_price:.5f}"
    )
    return result


def open_sell_order(symbol: str, sl_price: float, tp_price: float,
                    lot=None, comment="GoldBot_SELL"):
    lot     = lot or config.LOT_SIZE_GOLD
    lot     = _normalize_lot(symbol, lot)
    comment = _clean_comment(comment)

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log_event("ERROR", f"SELL fail [{symbol}] — price nahi mili.")
        return None

    bid = tick.bid
    sl_price, tp_price = _enforce_stop_level(
        symbol, bid, sl_price, tp_price, is_buy=False
    )

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       float(lot),
        "type":         mt5.ORDER_TYPE_SELL,
        "price":        bid,
        "sl":           round(float(sl_price), 5),
        "tp":           round(float(tp_price), 5),
        "deviation":    20,
        "magic":        123456,
        "comment":      comment,
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    log_event("INFO",
        f"SELL request [{symbol}] "
        f"Lot:{lot} Bid:{bid:.5f} "
        f"SL:{sl_price:.5f} TP:{tp_price:.5f} "
        f"Comment:{comment} (len={len(comment)})"
    )

    check = mt5.order_check(req)
    if check is not None and check.retcode != mt5.TRADE_RETCODE_DONE \
            and check.retcode != 0:
        log_event("WARNING",
            f"SELL pre-check [{symbol}] retcode:{check.retcode} "
            f"comment:{check.comment}"
        )

    result = mt5.order_send(req)

    if result is None:
        log_event("ERROR",
            f"SELL fail [{symbol}] — order_send None: {mt5.last_error()}"
        )
        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_event("ERROR",
            f"SELL fail [{symbol}] retcode:{result.retcode} | {result.comment}"
        )
        return None

    log_event("INFO",
        f"SELL OK [{symbol}] Ticket:{result.order} "
        f"Bid:{bid:.5f} SL:{sl_price:.5f} TP:{tp_price:.5f}"
    )
    return result


def get_open_positions(symbol: str = None):
    if symbol:
        pos = mt5.positions_get(symbol=symbol)
    else:
        pos = mt5.positions_get()
    return list(pos) if pos else []
