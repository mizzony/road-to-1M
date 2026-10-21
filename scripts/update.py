#!/usr/bin/env python3
"""Weekly portfolio update.

Steps: load holdings -> get prices + FX -> value everything in AUD ->
build history -> forecast the 100K goal -> find analyst rating changes ->
write site/data.js (for the website) and site/data.json (for the email).

  python scripts/update.py --demo                      # fake data, no internet needed
  python scripts/update.py --holdings holdings.csv     # your real data
"""
import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text())
SITE = ROOT / "site"

DEMO_PRICES = {"AAPL": 230, "MSFT": 420, "NVDA": 140, "VOO": 540, "VGE.AX": 80,
               "PTT.BK": 33, "CPALL.BK": 55, "GC=F": 2650}
DEMO_FX = {"AUD": 1.0, "USD": 1.52, "THB": 0.045}


# ---------- input ----------
def load_holdings(path):
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("ticker")]
    for r in rows:
        r["quantity"] = float(r["quantity"])
        r["cost_per_unit"] = float(r.get("cost_per_unit") or 0)
        r["currency"] = r["currency"].strip().upper()
    return rows


# ---------- live data (Yahoo Finance via yfinance) ----------
def fetch_live(holdings):
    """Latest prices + FX, plus a weekly history of what your CURRENT holdings
    were worth over the last 6 months (so no private history file is needed)."""
    import yfinance as yf

    tickers = sorted({h["ticker"] for h in holdings})
    currencies = sorted({h["currency"] for h in holdings if h["currency"] != "AUD"})
    fx_tickers = [f"{c}AUD=X" for c in currencies]
    close = yf.download(tickers + fx_tickers, period="6mo", progress=False,
                        auto_adjust=False)["Close"].ffill().bfill()
    if close.empty:
        raise SystemExit("Could not download prices from Yahoo Finance (no internet, or a ticker is wrong).")
    missing = [t for t in tickers + fx_tickers if t not in close.columns or close[t].isna().all()]
    if missing:
        raise SystemExit(f"No prices for: {', '.join(missing)}. Check these tickers on finance.yahoo.com.")
    last = close.iloc[-1]
    prices = {t: float(last[t]) for t in tickers}
    fx = {"AUD": 1.0}
    fx.update({c: float(last[f"{c}AUD=X"]) for c in currencies})

    weekly = close.resample("W-FRI").last().dropna(how="all")
    history = []
    for idx, row in weekly.iterrows():
        total = 0.0
        for h in holdings:
            rate = 1.0 if h["currency"] == "AUD" else float(row[f"{h['currency']}AUD=X"])
            total += h["quantity"] * float(row[h["ticker"]]) * rate
        history.append({"date": idx.date().isoformat(), "total_aud": round(total)})
    return prices, fx, history


def fetch_rating_changes(holdings, days):
    import pandas as pd
    import yfinance as yf

    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for h in holdings:
        if h["asset_class"].lower() != "us share":
            continue
        try:
            df = yf.Ticker(h["ticker"]).upgrades_downgrades
        except Exception:
            continue
        if df is None or df.empty:
            continue
        df = df.reset_index()
        df["GradeDate"] = pd.to_datetime(df["GradeDate"], utc=True)
        for _, r in df[df["GradeDate"] >= since].iterrows():
            out.append({
                "date": r["GradeDate"].date().isoformat(),
                "ticker": h["ticker"], "name": h["name"],
                "firm": str(r.get("Firm", "")),
                "action": str(r.get("Action", "")),
                "from": str(r.get("FromGrade", "") or ""),
                "to": str(r.get("ToGrade", "") or ""),
            })
    return out


# ---------- demo data ----------
def demo_rating_changes(today):
    d = lambda n: (today - timedelta(days=n)).isoformat()
    return [
        {"date": d(1), "ticker": "NVDA", "name": "Nvidia", "firm": "JP Morgan",
         "action": "main", "from": "Overweight", "to": "Overweight"},
        {"date": d(3), "ticker": "AAPL", "name": "Apple", "firm": "Morgan Stanley",
         "action": "up", "from": "Equal-Weight", "to": "Overweight"},
        {"date": d(5), "ticker": "MSFT", "name": "Microsoft", "firm": "Small Cap Research",
         "action": "down", "from": "Buy", "to": "Hold"},
    ]


def demo_history(today, end_value):
    rng = random.Random(42)
    weeks = 26
    start = end_value * 0.68
    rows = []
    for i in range(weeks + 1):
        d = today - timedelta(weeks=weeks - i)
        base = start + (end_value - start) * i / weeks
        noise = 0 if i == weeks else rng.uniform(-0.025, 0.025) * base
        rows.append({"date": d.isoformat(), "total_aud": round(base + noise)})
    return rows


# ---------- forecast ----------
def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def forecast(current, today):
    goal = CONFIG["goal_aud"]
    target = date.fromisoformat(CONFIG["target_date"])
    months = max(1, (target.year - today.year) * 12 + target.month - today.month)
    scenarios = []
    for s in CONFIG["scenarios"]:
        r = (1 + s["annual_return"]) ** (1 / 12) - 1
        v, path, hit = current, [], None
        for m in range(1, 61):
            v = v * (1 + r) + s["monthly"]
            if m <= months:
                path.append({"month": add_months(today, m).strftime("%Y-%m"), "value": round(v)})
            if hit is None and v >= goal:
                hit = add_months(today, m).strftime("%b %Y")
        scenarios.append({**s, "value_at_target": path[-1]["value"], "goal_reached": hit,
                          "path": path})

    # Monthly deposit needed to hit the goal on the target date (Normal return)
    normal = next((s for s in CONFIG["scenarios"] if s["name"] == "Normal"), CONFIG["scenarios"][0])
    r = (1 + normal["annual_return"]) ** (1 / 12) - 1
    if r == 0:
        needed = (goal - current) / months
    else:
        g = (1 + r) ** months
        needed = (goal - current * g) * r / (g - 1)
    return {"months_left": months, "required_monthly": max(0, round(needed)),
            "scenarios": scenarios}


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="use fake demo data")
    ap.add_argument("--holdings", default=str(ROOT / "holdings.csv"))
    args = ap.parse_args()

    today = date.today()
    if args.demo:
        holdings = load_holdings(ROOT / "holdings.example.csv")
        prices, fx = DEMO_PRICES, DEMO_FX
    else:
        holdings = load_holdings(args.holdings)
        prices, fx, live_history = fetch_live(holdings)

    rows, total, cost = [], 0.0, 0.0
    for h in holdings:
        rate = fx[h["currency"]]
        value = h["quantity"] * prices[h["ticker"]] * rate
        c = h["quantity"] * h["cost_per_unit"] * rate  # cost at today's FX (simple)
        total += value
        cost += c
        rows.append({"ticker": h["ticker"], "name": h["name"], "asset_class": h["asset_class"],
                     "quantity": h["quantity"], "price": round(prices[h["ticker"]], 2),
                     "currency": h["currency"], "value_aud": round(value),
                     "gain_aud": round(value - c),
                     "gain_pct": round((value - c) / c * 100, 1) if c else None})
    for r in rows:
        r["weight_pct"] = round(r["value_aud"] / total * 100, 1)
    rows.sort(key=lambda r: -r["value_aud"])

    allocation = {}
    for r in rows:
        allocation[r["asset_class"]] = allocation.get(r["asset_class"], 0) + r["value_aud"]

    if args.demo:
        history = demo_history(today, total)
        changes = demo_rating_changes(today)
    else:
        history = live_history
        if history and history[-1]["date"] != today.isoformat():
            history.append({"date": today.isoformat(), "total_aud": round(total)})
        changes = fetch_rating_changes(holdings, CONFIG["rating_lookback_days"])

    key = [f.lower() for f in CONFIG["key_firms"]]
    for c in changes:
        c["key_firm"] = any(k in c["firm"].lower() for k in key)
    changes.sort(key=lambda c: c["date"], reverse=True)

    week_ago = [h for h in history if h["date"] <= (today - timedelta(days=6)).isoformat()]
    week_change = round(total - week_ago[-1]["total_aud"]) if week_ago else None

    goal = CONFIG["goal_aud"]
    data = {
        "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
        "mode": "demo" if args.demo else "live",
        "goal_aud": goal, "target_date": CONFIG["target_date"],
        "total_aud": round(total), "cost_aud": round(cost),
        "gain_aud": round(total - cost),
        "gain_pct": round((total - cost) / cost * 100, 1) if cost else None,
        "progress_pct": round(min(total / goal * 100, 100), 1),
        "gap_aud": max(0, round(goal - total)),
        "week_change_aud": week_change,
        "fx": fx, "holdings": rows,
        "allocation": [{"asset_class": k, "value_aud": v, "pct": round(v / total * 100, 1)}
                       for k, v in sorted(allocation.items(), key=lambda kv: -kv[1])],
        "history": history,
        "forecast": forecast(total, today),
        "rating_changes": changes,
        "site_url": CONFIG.get("site_url", ""),
    }

    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, indent=2))
    (SITE / "data.js").write_text("window.PORTFOLIO_DATA = " + json.dumps(data) + ";\n")
    print(f"[{data['mode']}] Total ${total:,.0f} AUD — {data['progress_pct']}% of ${goal:,.0f}")


if __name__ == "__main__":
    main()
