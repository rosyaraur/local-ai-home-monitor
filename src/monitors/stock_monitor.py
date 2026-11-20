import json
import os
import sys
import urllib.request
from datetime import datetime

from common.notifier import send_alert

STATE_FILE = os.path.expanduser("~/stock_alert_state.json")

# Configure your tickers and alert rules (set any rule to None to disable it)
WATCHLIST = {
    # Major Indices
    "^GSPC": {"name": "S&P 500",    "below": None, "above": None, "pct_change": 5.0},
    "^DJI":  {"name": "Dow Jones",  "below": None, "above": None, "pct_change": 5.0},
    "^IXIC": {"name": "NASDAQ",     "below": None, "above": None, "pct_change": 5.0},
    # Major Stocks
    "AAPL":  {"name": "Apple",      "below": None, "above": None, "pct_change": 5.0},
    "MSFT":  {"name": "Microsoft",  "below": None, "above": None, "pct_change": 5.0},
    "NVDA":  {"name": "NVIDIA",     "below": None, "above": None, "pct_change": 5.0},
    "GOOGL": {"name": "Alphabet",   "below": None, "above": None, "pct_change": 5.0},
    "AMZN":  {"name": "Amazon",     "below": None, "above": None, "pct_change": 5.0},
    "META":  {"name": "Meta",       "below": None, "above": None, "pct_change": 5.0},
    "TSLA":  {"name": "Tesla",      "below": None, "above": None, "pct_change": 5.0},
}

def fetch_quote(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())

    meta = data["chart"]["result"][0]["meta"]
    price = float(meta["regularMarketPrice"])
    prev_close = float(meta.get("chartPreviousClose") or meta.get("previousClose"))
    pct = ((price - prev_close) / prev_close) * 100.0 if prev_close else 0.0
    return price, prev_close, pct


def load_state():
    today = datetime.now().strftime("%Y-%m-%d")
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            if state.get("date") == today:
                return state
        except Exception:
            pass
    return {"date": today, "sent": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def main():
    force_summary = "--summary" in sys.argv
    state = load_state()
    alerts = []
    summary_lines = []

    for ticker, rules in WATCHLIST.items():
        try:
            price, prev_close, pct = fetch_quote(ticker)
        except Exception as e:
            print(f"[{ticker}] Failed to fetch quote: {e}", flush=True)
            continue

        line = f"{ticker}: ${price:.2f} ({pct:+.2f}% vs prev close ${prev_close:.2f})"
        summary_lines.append(line)
        print(line, flush=True)

        triggers = []
        if rules.get("below") is not None and price <= rules["below"]:
            triggers.append(f"dropped below ${rules['below']:.2f}")
        if rules.get("above") is not None and price >= rules["above"]:
            triggers.append(f"rose above ${rules['above']:.2f}")
        if rules.get("pct_change") is not None and abs(pct) >= rules["pct_change"]:
            direction = "up" if pct > 0 else "down"
            triggers.append(f"moved {direction} {abs(pct):.2f}% (>= {rules['pct_change']}%)")

        for reason in triggers:
            alert_key = f"{ticker}:{reason.split()[0]}"
            if alert_key not in state["sent"]:
                alerts.append(f"- {ticker}: ${price:.2f} ({pct:+.2f}%) -> {reason}")
                state["sent"].append(alert_key)

    if alerts:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        send_alert(
            subject=f"[Beelink Stocks] Alert Triggered ({ts})",
            body="Stock threshold(s) triggered:\n\n" + "\n".join(alerts) + "\n\nFull Watchlist:\n" + "\n".join(summary_lines),
        )
        save_state(state)
    elif force_summary and summary_lines:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        send_alert(
            subject=f"[Beelink Stocks] Watchlist Summary ({ts})",
            body="Current watchlist snapshot:\n\n" + "\n".join(summary_lines),
        )


if __name__ == "__main__":
    main()
