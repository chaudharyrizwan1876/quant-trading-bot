# GoldBot — Automated Trading Bot (MT5)

Python-based automated trading bot for **MetaTrader 5**, trading **Gold (XAUUSDm)** and **Forex pairs** (EUR/GBP/JPY/AUD/CAD) using a mix of custom Liquidity Sweep, ICT/SMC (Order Blocks, FVG, BOS/CHOCH), and AMD (Accumulation-Manipulation-Distribution) strategies — plus live news filtering, dynamic risk-based lot sizing, and a web dashboard.

⚠️ **Disclaimer:** This is an experimental trading bot for educational/demo purposes. Trading involves real financial risk. Use on a demo account first. Not financial advice.

---

## Features

- **Gold Strategy** (`strategy_gold.py`) — H1/M30 trend, M15 zones, ATR-based SL, session-aware
- **ICT/SMC Strategy** (`strategy_ict.py`) — Order Blocks, FVG, Break-and-Retest, Kill Zones
- **AMD Strategy** (`strategy_amd.py`) — Standalone Accumulation-Manipulation-Distribution pattern
- **Dynamic Risk Management** (`risk_manager.py`) — Equity-based 1% risk per trade, correlation filter, daily loss limit, spread filter
- **News Filter** (`news_reader.py`) — Forex Factory high-impact news pause/trade logic
- **Trade Management** (`trade_manager.py`) — Break-even, partial close, SL trailing, weekend auto-close
- **Trade Memory** (`trade_memory.py`) — Blocks patterns/symbols after repeated losses
- **Live Dashboard** (`dashboard/`) — Web UI showing live prices, open trades, and history

---

## Project Structure

```
gold_bot/
├── main.py                # Entry point — runs the bot loop
├── config.py               # All settings (risk %, sessions, symbols, etc.)
├── mt5_connector.py         # MT5 connection, orders, candle data
├── strategy_gold.py         # Gold strategy
├── strategy_ict.py          # ICT/SMC strategy (Forex)
├── strategy_amd.py          # Standalone AMD strategy
├── indicators.py            # BOS/CHOCH, Order Blocks, FVG helpers
├── risk_manager.py          # Lot sizing, correlation, daily loss limit
├── trade_manager.py         # BE/trail/partial-close/weekend-close
├── trade_memory.py          # Pattern/symbol loss-blocking memory
├── news_reader.py           # Forex Factory news fetch + caching
├── logger.py                # Logging to console + CSV
├── dashboard/
│   ├── dashboard.py         # Local web server (Flask-free, stdlib)
│   └── dashboard.html       # Live dashboard UI
└── data/                    # Logs, trade history, news cache (gitignored)
```

---

## Setup

1. Install Python 3.10+ and MetaTrader 5 (Windows).
2. Install dependencies:
   ```bash
   pip install MetaTrader5 pandas
   ```
3. Copy `config.example.py` to `config.py` and fill in your MT5 login details:
   ```python
   MT5_LOGIN    = "YOUR_ACCOUNT_NUMBER"
   MT5_PASSWORD = "YOUR_PASSWORD"
   MT5_SERVER   = "YOUR_BROKER_SERVER"
   ```
4. Run the bot:
   ```bash
   python main.py
   ```
5. (Optional) Run the dashboard in a separate terminal:
   ```bash
   cd dashboard
   python dashboard.py
   ```
   Then open `http://localhost:5000` in your browser.

---

## ⚠️ Security Note

`config.py` contains your **MT5 login, password, and server** in plain text. This file is listed in `.gitignore` and must **never** be committed to GitHub. If you've already committed it, rotate your MT5 password immediately and remove it from git history (see below).

---

## License

Private/personal project — no license granted for redistribution.
