# Quant Trading Bot

Python-based algorithmic trading engine for **MetaTrader 5 (MT5)** that trades **Gold (XAUUSD)** and **Forex pairs** using a combination of custom Liquidity Sweep, Smart Money Concepts (SMC), ICT concepts, AMD (Accumulation-Manipulation-Distribution), and advanced risk management. The project is designed with an AI-ready architecture for future machine learning integration.

> ⚠️ **Disclaimer:** This project is intended for educational, research, and demo purposes. Trading financial markets involves significant risk. Always test on a demo account before using real funds. This is **not financial advice**.

---

# Features

* **Gold Strategy** (`strategy_gold.py`) — Multi-timeframe trend analysis, ATR-based Stop Loss, session-aware execution.
* **Silver Bullet Strategy** (`strategy_silver_bullet.py`) — ICT Silver Bullet session-based trading logic.
* **AMD Strategy** (`strategy_amd.py`) — Accumulation-Manipulation-Distribution pattern detection.
* **Dynamic Risk Management** (`risk_manager.py`) — Equity-based risk calculation, spread filter, daily loss limits, and correlation filtering.
* **News Filter** (`news_reader.py`) — Economic news filtering to avoid high-impact events.
* **Trade Management** (`trade_manager.py`) — Automatic Break Even, Trailing Stop, Partial Close, and intelligent trade management.
* **Trade Memory** (`trade_memory.py`) — Learns from repeated losing conditions to avoid similar low-probability setups.
* **Live Dashboard** (`dashboard/`) — Local dashboard for monitoring trades and market activity.
* **AI-Ready Architecture** — Modular design prepared for future AI and machine learning integration.

---

# Project Structure

```text
quant-trading-bot/
├── main.py
├── config.py
├── config.example.py
├── mt5_connector.py
├── strategy_gold.py
├── strategy_silver_bullet.py
├── strategy_amd.py
├── indicators.py
├── risk_manager.py
├── trade_manager.py
├── trade_memory.py
├── news_reader.py
├── logger.py
├── dashboard/
│   ├── dashboard.py
│   └── dashboard.html
├── backtesting/
├── requirements.txt
└── README.md
```

---

# Installation

## 1. Install Python

Install **Python 3.10 or later**.

## 2. Install MetaTrader 5

Install MetaTrader 5 and log in to your trading account (Demo recommended).

## 3. Install Dependencies like python and other libraries

```bash
pip install -r requirements.txt
```

## 4. Configure the Bot

Copy:

```text
config.example.py
```

to:

```text
config.py
```

Then update your MT5 credentials and bot configuration.

## 5. Run the Bot

Linux/macOS:

```bash
python main.py
```

Windows:

```bash
py main.py
```

## 6. Run Dashboard (Optional)

```bash
cd dashboard
python dashboard.py
```

Then open:

```text
http://localhost:5000
```

---

# Risk Management

The bot supports advanced risk management features including:

* Dynamic lot sizing
* Configurable account risk
* Maximum daily loss protection
* Spread filtering
* Session filtering
* Break Even automation
* Partial profit taking
* Intelligent trade management

---

# Supported Markets

* Gold (XAUUSD)
* Major Forex pairs
* Additional symbols can be added through configuration.

---

# Roadmap

### Version 0.2

* Strategy optimization
* Performance improvements
* Better market structure detection

### Version 0.3

* Advanced backtesting engine
* Performance analytics
* Strategy comparison tools

### Version 0.4

* AI-assisted trade filtering
* Adaptive market regime detection
* Probability-based trade scoring

### Version 1.0

* Production-ready release
* VPS deployment support
* Complete AI integration
* Multi-broker support
* Advanced dashboard

---

# Security

Never commit the following files to GitHub:

* `config.py`
* `.env`
* API keys
* Broker credentials
* Account passwords

Always use `config.example.py` as the public template.

---

# License

This repository is a private project intended for personal research and development. Redistribution or commercial use is not permitted without permission.
