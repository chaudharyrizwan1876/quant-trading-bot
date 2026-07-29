# ============================================================
#  backtesting/data_loader.py — Historical candle loader
# ============================================================
#
#  Do source support karta hai:
#    1. Local CSV cache (data/backtest/<symbol>_<tf>.csv) — fast,
#       reproducible, MT5 ki zaroorat nahi.
#    2. MT5 se live fetch (mt5.copy_rates_range) — cache banane
#       ke liye. Guarded import — MT5 na ho to bhi module load hota
#       hai (CSV replay CI/dev machine pe bhi chalta hai).
#
#  Multi-timeframe aligned slicing engine.py karta hai; yahan sirf
#  raw OHLCV load/normalize hota hai.
# ============================================================

import os
import pandas as pd

CACHE_DIR = os.path.join("data", "backtest")

_TF_TABLE = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440,
}


def _cache_path(symbol: str, tf: str) -> str:
    return os.path.join(CACHE_DIR, f"{symbol}_{tf}.csv")


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["time"]):
        # epoch seconds ya ISO string dono handle
        if pd.api.types.is_numeric_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        else:
            df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def save_cache(symbol: str, tf: str, df: pd.DataFrame):
    os.makedirs(CACHE_DIR, exist_ok=True)
    df.to_csv(_cache_path(symbol, tf), index=False)


def load_cache(symbol: str, tf: str) -> pd.DataFrame:
    path = _cache_path(symbol, tf)
    if not os.path.exists(path):
        return None
    return _normalize(pd.read_csv(path))


def fetch_from_mt5(symbol: str, tf: str, start, end,
                   login=None, password=None, server=None) -> pd.DataFrame:
    """
    MT5 se historical candles fetch kar ke cache karta hai.
    start/end: datetime (UTC). Returns normalized DataFrame.
    Warning: yeh live terminal se connect karta hai.
    """
    import MetaTrader5 as mt5

    tf_map = {
        "M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }
    if tf not in tf_map:
        raise ValueError(f"Unknown timeframe: {tf}")

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize fail: {mt5.last_error()}")
    try:
        if login:
            mt5.login(login=login, password=password, server=server)
        rates = mt5.copy_rates_range(symbol, tf_map[tf], start, end)
    finally:
        mt5.shutdown()

    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates for {symbol} {tf} in given range")

    df = _normalize(pd.DataFrame(rates))
    save_cache(symbol, tf, df)
    return df


def load(symbol: str, tf: str, prefer_cache: bool = True) -> pd.DataFrame:
    """Cache se load karo (backtest ka default path)."""
    df = load_cache(symbol, tf)
    if df is None:
        raise FileNotFoundError(
            f"No cached data for {symbol} {tf}. "
            f"Run fetch_from_mt5() once to build {_cache_path(symbol, tf)}."
        )
    return df
