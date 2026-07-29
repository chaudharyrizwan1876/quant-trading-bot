# ============================================================
#  indicators/volatility.py — ATR / ADX / RSI
#  Consolidated: pehle yeh teeno strategies/gold_hybrid.py mein
#  private (_calc_atr/_check_adx/_calc_rsi) the — koi aur
#  strategy inhe reuse nahi kar sakti thi. Ab shared indicator
#  utils hain, jo kisi bhi strategy/backtest se use ho sakte hain.
#  Logic bit-for-bit same hai — sirf location badla hai.
# ============================================================


def calc_atr(df, period: int = 14) -> float:
    """Average True Range — last `period` closed-candle true ranges ka average."""
    if df is None or len(df) < period + 2:
        return 0.0
    r = df.tail(period + 1).reset_index(drop=True)
    trs = []
    for i in range(1, len(r)):
        h, l, pc = r.iloc[i]["high"], r.iloc[i]["low"], r.iloc[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else 0.0


def calc_adx(df, period: int = 14) -> float:
    """
    ADX (trend strength). Caller apni tarafse insufficient-data
    guard rakhe (jaisa pehle _check_adx mein tha) — yahan sirf
    raw value calculate hoti hai.
    """
    if df is None or len(df) < period + 1:
        return 0.0
    r = df.tail(period + 1).reset_index(drop=True)
    pdm, mdm, trs = [], [], []
    for i in range(1, len(r)):
        h, l = r.iloc[i]["high"], r.iloc[i]["low"]
        ph, pl, pc = r.iloc[i - 1]["high"], r.iloc[i - 1]["low"], r.iloc[i - 1]["close"]
        up, dn = h - ph, pl - l
        pdm.append(up if up > dn and up > 0 else 0)
        mdm.append(dn if dn > up and dn > 0 else 0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    ts = sum(trs)
    if ts == 0:
        return 0.0
    pdi, mdi = sum(pdm) / ts * 100, sum(mdm) / ts * 100
    return abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0.0


def calc_rsi(df, period: int = 14) -> float:
    """Relative Strength Index on closed candles."""
    if df is None or len(df) < period + 2:
        return 50.0
    closes = df["close"].tail(period + 1).reset_index(drop=True)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain, avg_loss = sum(gains) / period, sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
