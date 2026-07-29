# Quant Trading Bot

Python-based algorithmic trading engine for **MetaTrader 5 (MT5)** that trades **Gold (XAUUSD)** and **Forex pairs** using a combination of custom Liquidity Sweep, Smart Money Concepts (SMC), ICT concepts, AMD (Accumulation-Manipulation-Distribution), and advanced risk management. The project is designed with an AI-ready architecture for future machine learning integration.

> ⚠️ **Disclaimer:** This project is intended for educational, research, and demo purposes. Trading financial markets involves significant risk. Always test on a demo account before using real funds. This is **not financial advice**.

---

# Features

* **Gold Hybrid Strategy** (`strategies/gold_hybrid.py`) — Multi-timeframe SMC/ICT engine: majority-vote trend (H1/M30/M15 + momentum override), Order Blocks, FVGs, liquidity sweeps, an institutional-footprint detector (equal highs/lows sweep + displacement + volume spike), AMD, break-retest, kill zones, ATR-based stops.
* **AMD Strategy** (`strategies/amd.py`) — Standalone Accumulation-Manipulation-Distribution (Power-of-3) pattern.
* **Silver Bullet Strategy** (`strategies/silver_bullet.py`) — ICT Silver Bullet time-window liquidity-sweep + FVG reversal.
* **Confidence / Decision Layer** (`ai/confidence.py`) — Every candidate setup is scored to a **bounded 0–99% confidence** with a **structured reasons list**; only setups above `MIN_CONFIDENCE` execute (quality over quantity). This is the "AI as evaluator, not signal generator" layer, with a documented extension point for a trained ML win-probability model.
* **Dynamic Risk Engine** (`risk/`) — 1% equity hard-cap with SL-shrink, **confidence-scaled position sizing**, **consecutive-loss circuit breaker**, daily-loss limit, global exposure guard, spread filter.
* **Robust Execution** (`market_data/mt5_connector.py`) — Order sender with **filling-mode fallback (IOC→FOK→RETURN)** and **requote/price-change retry**.
* **News Filter** (`news/news_reader.py`) — High-impact economic-event filtering.
* **Trade Management** (`execution/trade_manager.py`) — Break-even, SL trailing, partial close, weekend close.
* **Adaptive Trade Memory** (`memory/trade_memory.py`) — Pattern/symbol/hour win-rate learning + loss-streak blocking.
* **Backtesting Engine** (`backtesting/`) — Bar-replay of the **live strategy code** via a non-invasive frozen clock, conservative fill simulator (SL/TP/BE/partial), and R-multiple performance metrics.
* **Live Dashboard** (`dashboard/`) — Local monitoring UI.

---

# Project Structure

```text
gold_bot/
├── main.py                     # orchestration loop
├── config.py / config.example.py
├── logger.py                   # buffered, size-rotated logging
├── ai/
│   └── confidence.py           # bounded confidence % + reasons (decision layer)
├── strategies/
│   ├── gold_hybrid.py          # primary Gold SMC/ICT engine
│   ├── amd.py
│   └── silver_bullet.py
├── indicators/
│   ├── smc.py                  # structure, OB, FVG, liquidity
│   └── volatility.py           # ATR / ADX / RSI (shared)
├── sessions/
│   └── kill_zones.py           # session / kill-zone detection (clock-injectable)
├── risk/
│   └── risk_manager.py         # sizing, SL cap, breaker, exposure guards
├── execution/
│   └── trade_manager.py        # BE / trail / partial / weekend close
├── market_data/
│   └── mt5_connector.py        # MT5 connection, feed, robust order sender
├── memory/
│   └── trade_memory.py         # adaptive learning
├── news/
│   └── news_reader.py
├── backtesting/
│   ├── data_loader.py          # MT5 fetch + CSV cache
│   ├── clock.py                # frozen-clock replay adapter
│   ├── simulator.py            # fill/SL/TP/BE/partial simulation
│   ├── metrics.py              # win rate, expectancy, drawdown, PF
│   ├── engine.py               # bar-replay runner
│   ├── run_backtest.py         # CLI
│   └── tests/                  # simulator + engine unit tests
├── dashboard/
├── requirements.txt
└── README.md
```

---

# Backtesting

Build a historical cache once (needs MT5 running), then replay offline:

```bash
python -m backtesting.run_backtest --fetch --days 60
python -m backtesting.run_backtest --run
```

`--no-gate` disables the confidence filter to inspect the raw strategy. Run the
unit tests with:

```bash
python -m backtesting.tests.test_simulator
python -m backtesting.tests.test_engine
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

From the **project root** (packages are resolved relative to it):

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

**Done**

* Modular package architecture (`ai/`, `strategies/`, `risk/`, `execution/`, `market_data/`, `indicators/`, `sessions/`, `memory/`, `news/`, `backtesting/`)
* Bounded confidence % + structured reasons decision layer
* Bar-replay backtesting engine with conservative fill simulator and R-multiple metrics
* Confidence-scaled sizing, consecutive-loss circuit breaker, exposure guard
* Robust order execution (filling-mode fallback + requote retry)
* Buffered, size-rotated logging

**Next**

* **Trained ML win-probability model** (`ai/confidence.py` extension point). Prerequisite: a meaningful labelled dataset. Live history is currently ~tens of trades — far too few (overfit risk). Use the backtesting engine to accumulate and validate outcomes **before** any model gates real trades. Until then the confidence engine stays deterministic and fully explainable.
* Walk-forward optimization and per-session performance analytics on top of the backtester
* Move MT5 credentials out of `config.py` into environment variables
* VPS deployment + multi-broker support

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
