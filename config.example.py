# ============================================================
#  config.example.py — Template
#  Ise copy karke "config.py" naam se save karo, phir apni
#  MT5 details bharo. config.py GitHub par kabhi push NAHI hogi
#  (.gitignore mein already excluded hai).
# ============================================================

MT5_LOGIN    = 0              # Apna MT5 account number
MT5_PASSWORD = "YOUR_PASSWORD_HERE"
MT5_SERVER   = "YOUR_BROKER_SERVER"   # e.g. "Exness-MT5Trial15"

SYMBOL_GOLD = "XAUUSDm"
SYMBOL_ICT  = ["EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "USDCADm"]

# Baaki saari settings config.py mein dekho — risk %, sessions,
# ATR multipliers, etc. Yeh file sirf login template ke liye hai.

# ── Key runtime tunables (defaults config.py mein set hain) ──
# MIN_CONFIDENCE              = 66.0   # 0..99; is se upar hi trade (quality gate)
# CONFIDENCE_GATING_ENABLED  = True    # False → confidence sirf log/rank, no block
# RISK_PERCENT               = 0.01    # 1% equity hard cap per trade
# RISK_PERCENT_MIN           = 0.005   # confidence-scaled sizing ka floor
# MAX_CONSECUTIVE_LOSSES     = 3       # itni lagataar losses → cooldown breaker
# CONSECUTIVE_LOSS_COOLDOWN_MINS = 120
# MAX_DAILY_LOSS_PCT         = 0.03    # 3% daily loss → trading paused
# MAX_OPEN_TRADES            = 3       # global open-position cap
# PARTIAL_CLOSE_ENABLED      = False   # backtest: aggressive partial hurt edge
# MAX_HOLD_MINUTES           = 90      # scalp: itne min baad force-close (0=off)
# TIME_STOP_MAX_PROFIT_R     = 1.0     # time-stop sirf tab jab profit < is R (winners run)
# TRAIL_MODE                 = "giveback"  # trend-rider trail (None = fixed scalp trail)
# TRAIL_ACTIVATE_R           = 3.0     # itne R ke baad trailing shuru
# TRAIL_GIVEBACK_R           = 1.5     # peak se itna R deke exit (trend ride)
# STRATEGY_MODE              = "momentum"  # "momentum" (scalper) ya "swing" (old stack)
