#!/usr/bin/env python3
"""Weekly portfolio update.

Steps: load holdings -> get prices + FX -> value everything in AUD ->
build history -> forecast each goal -> find analyst rating changes ->
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
def _num(v):
    v = (v or "").strip().replace(",", "")
    return float(v) if v else None


def load_holdings(path):
    """Columns: account,ticker,name,asset_class,quantity,cost_per_unit,currency,
    total_cost,snapshot_value,snapshot_date.
    - Give quantity + cost_per_unit when you know them.
    - For fractional shares (e.g. Dime) or physical gold, leave quantity blank and give
      snapshot_value + snapshot_date (value in the holding's currency on that day);
      quantity is then worked out from that day's price.
    - total_cost (holding currency) overrides quantity * cost_per_unit."""
    with open(path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if (r.get("ticker") or "").strip()]
    for r in rows:
        r["ticker"] = r["ticker"].strip()
        r["account"] = (r.get("account") or "").strip()
        r["quantity"] = _num(r.get("quantity"))
        r["cost_per_unit"] = _num(r.get("cost_per_unit")) or 0.0
        r["total_cost"] = _num(r.get("total_cost"))
        r["snapshot_value"] = _num(r.get("snapshot_value"))
        r["snapshot_date"] = (r.get("snapshot_date") or "").strip()
        r["currency"] = r["currency"].strip().upper()
        if r["quantity"] is None and not (r["snapshot_value"] and r["snapshot_date"]):
            raise SystemExit(f"::error::{r['ticker']}: give either quantity, or snapshot_value + snapshot_date")
    return rows


def cost_of(h):
    """Total cost in the holding's currency."""
    if h["total_cost"] is not None:
        return h["total_cost"]
    return (h["quantity"] or 0) * h["cost_per_unit"]


# ---------- live data (Yahoo Finance via yfinance) ----------
def fetch_live(holdings):
    """Latest prices + FX, plus a weekly history of what your CURRENT holdings
    were worth over the last 6 months (so no private history file is needed).
    Holdings with an unknown ticker are skipped with a warning."""
    import yfinance as yf

    tickers = sorted({h["ticker"] for h in holdings})
    currencies = sorted({h["currency"] for h in holdings if h["currency"] != "AUD"})
    fx_tickers = [f"{c}AUD=X" for c in currencies]
    snap_dates = [h["snapshot_date"] for h in holdings if h["snapshot_date"]]
    start = min([(date.today() - timedelta(days=183)).isoformat()] + snap_dates)
    start = (date.fromisoformat(start) - timedelta(days=7)).isoformat()
    close = yf.download(tickers + fx_tickers, start=start, progress=False,
                        auto_adjust=False)["Close"].ffill()
    if close.empty:
        raise SystemExit("::error::Could not download prices from Yahoo Finance (no internet?).")
    bad_fx = [t for t in fx_tickers if t not in close.columns or close[t].isna().all()]
    if bad_fx:
        raise SystemExit(f"::error::No exchange rate for: {', '.join(bad_fx)}")
    missing = [t for t in tickers if t not in close.columns or close[t].isna().all()]
    if missing:
        print(f"::warning::No prices for {', '.join(missing)} - skipped. Check these tickers on finance.yahoo.com")
    holdings[:] = [h for h in holdings if h["ticker"] not in missing]
    tickers = [t for t in tickers if t not in missing]

    # Work out quantity for snapshot rows (fractional shares, physical gold)
    for h in holdings:
        if h["quantity"] is None:
            series = close[h["ticker"]].loc[:h["snapshot_date"]].dropna()
            price_then = float(series.iloc[-1]) if len(series) else float(close[h["ticker"]].dropna().iloc[0])
            h["quantity"] = h["snapshot_value"] / price_then

    last = close.iloc[-1]
    prices = {t: float(last[t]) for t in tickers}
    fx = {"AUD": 1.0}
    fx.update({c: float(last[f"{c}AUD=X"]) for c in currencies})
    week_ago = close.loc[:(date.today() - timedelta(days=7)).isoformat()]
    wk = week_ago.iloc[-1] if len(week_ago) else close.iloc[0]
    prev_prices = {t: float(wk[t]) if wk[t] == wk[t] else prices[t] for t in tickers}

    recent = close.loc[(date.today() - timedelta(days=183)).isoformat():]
    # Shares listed recently (e.g. SpaceX) have no earlier prices: use their first price
    weekly = recent.resample("W-FRI").last().dropna(how="all").ffill().bfill()
    history = []
    for idx, row in weekly.iterrows():
        total = 0.0
        for h in holdings:
            rate = 1.0 if h["currency"] == "AUD" else float(row[f"{h['currency']}AUD=X"])
            total += h["quantity"] * float(row[h["ticker"]]) * rate
        if idx.date() <= date.today():  # skip the unfinished current week (its label is a future Friday)
            history.append({"date": idx.date().isoformat(), "total_aud": round(total)})
    return prices, fx, history, prev_prices


def fetch_rating_changes(holdings, days):
    import pandas as pd
    import yfinance as yf

    since = datetime.now(timezone.utc) - timedelta(days=days)
    out, seen = [], set()
    for h in holdings:
        if h["asset_class"].lower() != "us share" or h["ticker"] in seen:
            continue
        seen.add(h["ticker"])
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


def fallback_sector(h):
    ac = h["asset_class"].lower()
    if ac == "gold":
        return "Gold", "Gold"
    if ac == "etf":
        return "ETF / Fund", "ETF"
    return "Other", ""


def fetch_profiles(holdings):
    """Sector and industry for each ticker (from Yahoo Finance)."""
    import yfinance as yf
    out = {}
    for h in holdings:
        t = h["ticker"]
        if t in out:
            continue
        sector, industry = fallback_sector(h)
        if sector == "Other":
            try:
                info = yf.Ticker(t).info or {}
                sector = info.get("sector") or sector
                industry = info.get("industry") or industry
            except Exception:
                pass
        out[t] = (sector, industry)
    return out


def fetch_news(items, days=7, per_ticker=2):
    """Latest headlines for the given (ticker, name) pairs. Handles old and new yfinance formats."""
    import yfinance as yf
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for t, name in items:
        try:
            raw = yf.Ticker(t).news or []
        except Exception:
            continue
        got = 0
        for n in raw:
            c = n.get("content", n)
            title = c.get("title")
            link = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or c.get("link")
            publisher = (c.get("provider") or {}).get("displayName") or c.get("publisher", "")
            when = c.get("pubDate") or c.get("providerPublishTime")
            try:
                dt = (datetime.fromtimestamp(when, timezone.utc) if isinstance(when, (int, float))
                      else datetime.fromisoformat(str(when).replace("Z", "+00:00")))
            except Exception:
                continue
            if not title or not link or dt < since:
                continue
            out.append({"ticker": t, "name": name, "title": title, "link": link,
                        "publisher": publisher, "date": dt.date().isoformat()})
            got += 1
            if got >= per_ticker:
                break
    out.sort(key=lambda n: n["date"], reverse=True)
    return out


# ---------- demo data ----------
DEMO_PREV_PRICES = {"AAPL": 222, "MSFT": 431, "NVDA": 131, "VOO": 533, "VGE.AX": 81,
                    "PTT.BK": 34, "CPALL.BK": 54, "GC=F": 2610}
DEMO_PROFILES = {"AAPL": ("Technology", "Consumer Electronics"), "MSFT": ("Technology", "Software"),
                 "NVDA": ("Technology", "Semiconductors"), "VOO": ("ETF / Fund", "ETF"),
                 "VGE.AX": ("ETF / Fund", "ETF"), "PTT.BK": ("Energy", "Oil & Gas"),
                 "CPALL.BK": ("Consumer Defensive", "Grocery Stores"), "GC=F": ("Gold", "Gold")}


def demo_news(today):
    d = lambda n: (today - timedelta(days=n)).isoformat()
    return [
        {"ticker": "NVDA", "name": "Nvidia", "title": "Example headline: chip demand stays strong into next quarter",
         "link": "https://finance.yahoo.com/quote/NVDA/news", "publisher": "Demo News", "date": d(1)},
        {"ticker": "MSFT", "name": "Microsoft", "title": "Example headline: cloud growth slows slightly",
         "link": "https://finance.yahoo.com/quote/MSFT/news", "publisher": "Demo News", "date": d(2)},
        {"ticker": "GC=F", "name": "Gold", "title": "Example headline: gold rises as the US dollar weakens",
         "link": "https://finance.yahoo.com/quote/GC=F/news", "publisher": "Demo News", "date": d(3)},
    ]
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


def forecast(current, today, goal, target_date):
    target = date.fromisoformat(target_date)
    months = max(1, (target.year - today.year) * 12 + target.month - today.month)
    scenarios = []
    for s in CONFIG["scenarios"]:
        r = (1 + s["annual_return"]) ** (1 / 12) - 1
        v, path, hit, hit_month = current, [], None, None
        for m in range(1, 181):
            v = v * (1 + r) + s["monthly"]
            if m <= months:
                path.append({"month": add_months(today, m).strftime("%Y-%m"), "value": round(v)})
            if hit is None and v >= goal:
                hit = add_months(today, m).strftime("%b %Y")
                hit_month = add_months(today, m).strftime("%Y-%m")
        scenarios.append({**s, "value_at_target": path[-1]["value"], "goal_reached": hit, "goal_reached_month": hit_month,
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


def on_track(fc, target_date):
    """On track = the Normal scenario (your usual monthly deposit) reaches the goal by the date."""
    n = next((x for x in fc["scenarios"] if x["name"] == "Normal"), fc["scenarios"][0])
    return bool(n.get("goal_reached_month") and n["goal_reached_month"] <= target_date[:7])


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="use fake demo data")
    ap.add_argument("--holdings", default=str(ROOT / "holdings.csv"))
    args = ap.parse_args()

    today = date.today()
    if args.demo:
        holdings = load_holdings(ROOT / "holdings.example.csv")
        prices, fx, prev_prices = DEMO_PRICES, DEMO_FX, DEMO_PREV_PRICES
        profiles = DEMO_PROFILES
    else:
        holdings = load_holdings(args.holdings)
        prices, fx, live_history, prev_prices = fetch_live(holdings)
        profiles = fetch_profiles(holdings)

    rows, total, cost = [], 0.0, 0.0
    for h in holdings:
        rate = fx[h["currency"]]
        value = h["quantity"] * prices[h["ticker"]] * rate
        c = cost_of(h) * rate  # cost at today's FX (simple)
        total += value
        cost += c
        rows.append({"ticker": h["ticker"], "name": h["name"], "asset_class": h["asset_class"],
                     "account": h.get("account", ""),
                     "quantity": round(h["quantity"], 4), "price": round(prices[h["ticker"]], 2),
                     "currency": h["currency"], "value_aud": round(value),
                     "gain_aud": round(value - c),
                     "gain_pct": round((value - c) / c * 100, 1) if c else None,
                     "cost_aud": round(c),
                     "sector": profiles.get(h["ticker"], fallback_sector(h))[0],
                     "industry": profiles.get(h["ticker"], fallback_sector(h))[1],
                     "week_pct": round((prices[h["ticker"]] / prev_prices[h["ticker"]] - 1) * 100, 1)
                                 if prev_prices.get(h["ticker"]) else None})
    for r in rows:
        r["weight_pct"] = round(r["value_aud"] / total * 100, 1)
    rows.sort(key=lambda r: -r["value_aud"])

    # Top movers: one line per stock (accounts merged)
    merged = {}
    for r in rows:
        m = merged.setdefault(r["ticker"], {"ticker": r["ticker"], "name": r["name"], "sector": r["sector"],
                                            "week_pct": r["week_pct"], "value_aud": 0, "gain_aud": 0, "cost_aud": 0})
        m["value_aud"] += r["value_aud"]; m["gain_aud"] += r["gain_aud"]; m["cost_aud"] += r["cost_aud"]
    for m in merged.values():
        m["gain_pct"] = round(m["gain_aud"] / m["cost_aud"] * 100, 1) if m["cost_aud"] else None
    def top(key, n=10):
        have = [m for m in merged.values() if m[key] is not None]
        up = sorted([m for m in have if m[key] > 0], key=lambda m: -m[key])[:n]
        down = sorted([m for m in have if m[key] < 0], key=lambda m: m[key])[:n]
        return {"gainers": up, "losers": down}
    movers = {"week": top("week_pct"), "total": top("gain_pct")}

    # By industry (sector)
    sec = {}
    for r in rows:
        x = sec.setdefault(r["sector"], {"sector": r["sector"], "value_aud": 0, "cost_aud": 0, "prev_aud": 0.0, "holdings": {}})
        x["value_aud"] += r["value_aud"]; x["cost_aud"] += r["cost_aud"]
        x["prev_aud"] += r["value_aud"] / (1 + (r["week_pct"] or 0) / 100)
        x["holdings"][r["ticker"]] = x["holdings"].get(r["ticker"], 0) + r["value_aud"]
    sectors = []
    for x in sec.values():
        sectors.append({"sector": x["sector"], "value_aud": x["value_aud"],
                        "pct": round(x["value_aud"] / total * 100, 1),
                        "week_pct": round((x["value_aud"] / x["prev_aud"] - 1) * 100, 1) if x["prev_aud"] else None,
                        "gain_aud": x["value_aud"] - x["cost_aud"],
                        "gain_pct": round((x["value_aud"] - x["cost_aud"]) / x["cost_aud"] * 100, 1) if x["cost_aud"] else None,
                        "top": [t for t, _ in sorted(x["holdings"].items(), key=lambda kv: -kv[1])[:4]]})
    sectors.sort(key=lambda x: -x["value_aud"])

    allocation = {}
    for r in rows:
        allocation[r["asset_class"]] = allocation.get(r["asset_class"], 0) + r["value_aud"]

    if args.demo:
        history = demo_history(today, total)
        changes = demo_rating_changes(today)
        news = demo_news(today)
    else:
        history = live_history
        if history and history[-1]["date"] != today.isoformat():
            history.append({"date": today.isoformat(), "total_aud": round(total)})
        changes = fetch_rating_changes(holdings, CONFIG["rating_lookback_days"])
        # News for: biggest movers this week, big holdings, and stocks with a major-bank rating change
        pick = [m["ticker"] for m in movers["week"]["gainers"][:3] + movers["week"]["losers"][:3]]
        pick += [t for t, _ in sorted(merged.items(), key=lambda kv: -kv[1]["value_aud"])[:3]]
        key = [f.lower() for f in CONFIG["key_firms"]]
        pick += [c["ticker"] for c in changes if any(k in c["firm"].lower() for k in key) and c["action"] in ("up", "down")]
        seen, items = set(), []
        for t in pick:
            if t not in seen and t != "GC=F":
                seen.add(t); items.append((t, merged[t]["name"]))
        news = fetch_news(items[:10])

    key = [f.lower() for f in CONFIG["key_firms"]]
    for c in changes:
        c["key_firm"] = any(k in c["firm"].lower() for k in key)
    changes.sort(key=lambda c: c["date"], reverse=True)

    week_ago = [h for h in history if h["date"] <= (today - timedelta(days=6)).isoformat()]
    week_change = round(total - week_ago[-1]["total_aud"]) if week_ago else None

    goals = []
    for g in CONFIG["goals"]:
        goals.append({**g,
                      "progress_pct": round(min(total / g["amount"] * 100, 100), 1),
                      "gap_aud": max(0, round(g["amount"] - total)),
                      "reached": total >= g["amount"],
                      "forecast": forecast(total, today, g["amount"], g["date"])})
        goals[-1]["on_track"] = on_track(goals[-1]["forecast"], g["date"])
        if g.get("stretch_date"):
            sf = forecast(total, today, g["amount"], g["stretch_date"])
            goals[-1]["stretch"] = {"date": g["stretch_date"], "required_monthly": sf["required_monthly"],
                                    "on_track": on_track(sf, g["stretch_date"])}
    active = next((g for g in goals if not g["reached"]), goals[-1])
    data = {
        "generated_at": datetime.now().strftime("%d %b %Y %H:%M"),
        "mode": "demo" if args.demo else "live",
        "goals": goals,
        # the next goal not yet reached (used for the headline)
        "goal_name": active["name"], "goal_aud": active["amount"], "target_date": active["date"],
        "progress_pct": active["progress_pct"], "gap_aud": active["gap_aud"],
        "forecast": active["forecast"],
        "total_aud": round(total), "cost_aud": round(cost),
        "gain_aud": round(total - cost),
        "gain_pct": round((total - cost) / cost * 100, 1) if cost else None,
        "week_change_aud": week_change,
        "fx": fx, "holdings": rows,
        "allocation": [{"asset_class": k, "value_aud": v, "pct": round(v / total * 100, 1)}
                       for k, v in sorted(allocation.items(), key=lambda kv: -kv[1])],
        "history": history,
        "rating_changes": changes,
        "movers": movers,
        "sectors": sectors,
        "news": news,
        "site_url": CONFIG.get("site_url", ""),
    }

    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, indent=2))
    (SITE / "data.js").write_text("window.PORTFOLIO_DATA = " + json.dumps(data) + ";\n")
    print(f"[{data['mode']}] Total ${total:,.0f} AUD — " +
          ", ".join(f"{g['progress_pct']}% of {g['name']}" for g in goals))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # show the error as a clear message in GitHub Actions
        import traceback
        traceback.print_exc()
        print(f"::error title=update.py failed::{type(e).__name__}: {e}")
        raise SystemExit(1)
