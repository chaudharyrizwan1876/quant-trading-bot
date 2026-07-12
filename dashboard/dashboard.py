# ============================================================
#  dashboard.py — GoldBot Live Dashboard Server
#  D:\gold_bot\dashboard\dashboard.py
#  Run: python dashboard.py
#  Browser: http://localhost:5000
# ============================================================

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import csv
from datetime import datetime, timezone, timedelta
import threading
import time

# MT5 import
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False

import config

# ─────────────────────────────────────────────
#  Pakistan Time (GMT+5)
# ─────────────────────────────────────────────
PKT = timedelta(hours=5)

def to_pkt(dt):
    if dt is None: return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + PKT).strftime("%d %b %Y  %I:%M:%S %p")

def now_pkt():
    return to_pkt(datetime.now(timezone.utc))

# ─────────────────────────────────────────────
#  MT5 Data Fetch
# ─────────────────────────────────────────────

def get_live_data():
    """MT5 se live prices aur open trades lo."""
    data = {
        "timestamp": now_pkt(),
        "prices":    {},
        "open":      [],
        "history":   [],
        "balance":   0,
        "equity":    0,
        "profit":    0,
    }

    if not MT5_AVAILABLE:
        return data

    if not mt5.initialize():
        return data

    try:
        # Account info
        acc = mt5.account_info()
        if acc:
            data["balance"] = round(acc.balance, 2)
            data["equity"]  = round(acc.equity,  2)
            data["profit"]  = round(acc.profit,  2)

        # Live prices
        symbols = [config.SYMBOL_GOLD] + config.SYMBOL_ICT
        for sym in symbols:
            tick = mt5.symbol_info_tick(sym)
            if tick:
                data["prices"][sym] = {
                    "bid": round(tick.bid, 5),
                    "ask": round(tick.ask, 5),
                }

        # Open positions
        positions = mt5.positions_get()
        if positions:
            for p in positions:
                open_time = datetime.fromtimestamp(
                    p.time, tz=timezone.utc)
                data["open"].append({
                    "ticket":  p.ticket,
                    "symbol":  p.symbol,
                    "type":    "BUY" if p.type == 0 else "SELL",
                    "lot":     p.volume,
                    "entry":   round(p.price_open, 5),
                    "current": round(p.price_current, 5),
                    "sl":      round(p.sl, 5),
                    "tp":      round(p.tp, 5),
                    "profit":  round(p.profit, 2),
                    "comment": p.comment,
                    "open_time": to_pkt(open_time),
                })

        # Trade history — last 7 days
        from_date = datetime.now(timezone.utc) - timedelta(days=7)
        deals = mt5.history_deals_get(from_date, datetime.now(timezone.utc))
        if deals:
            # Group by position_id
            pos_map = {}
            for d in deals:
                pid = d.position_id
                if pid not in pos_map:
                    pos_map[pid] = []
                pos_map[pid].append(d)

            for pid, deal_list in pos_map.items():
                if len(deal_list) < 2: continue
                open_d  = deal_list[0]
                close_d = deal_list[-1]

                ot = datetime.fromtimestamp(open_d.time,  tz=timezone.utc)
                ct = datetime.fromtimestamp(close_d.time, tz=timezone.utc)

                total_profit = sum(d.profit for d in deal_list)

                data["history"].append({
                    "ticket":     pid,
                    "symbol":     open_d.symbol,
                    "type":       "BUY" if open_d.type == 0 else "SELL",
                    "lot":        open_d.volume,
                    "entry":      round(open_d.price, 5),
                    "close":      round(close_d.price, 5),
                    "profit":     round(total_profit, 2),
                    "open_time":  to_pkt(ot),
                    "close_time": to_pkt(ct),
                    "close_ts":   close_d.time,  # Raw timestamp for sorting
                    "comment":    open_d.comment,
                })

            # Latest close time pehle — raw timestamp pe sort
            data["history"].sort(key=lambda x: x["close_ts"], reverse=True)
            for h in data["history"]:
                h.pop("close_ts", None)
            data["history"] = data["history"][:50]  # Last 50

    finally:
        mt5.shutdown()

    return data

# ─────────────────────────────────────────────
#  HTTP Server
# ─────────────────────────────────────────────

HTML_FILE = os.path.join(os.path.dirname(__file__), "dashboard.html")

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # Console quiet rakho

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/data":
            self._serve_data()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        try:
            with open(HTML_FILE, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500)
            self.end_headers()

    def _serve_data(self):
        try:
            data = get_live_data()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(500)
            self.end_headers()


def run_server(port=5000):
    server = HTTPServer(("", port), Handler)
    print(f"\n{'='*50}")
    print(f"  GoldBot Dashboard")
    print(f"  http://localhost:{port}")
    print(f"  Ctrl+C se band karo")
    print(f"{'='*50}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard band ho gaya.")
        server.shutdown()


if __name__ == "__main__":
    run_server()
