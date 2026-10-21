#!/usr/bin/env python3
"""Daily smart alerts. Sends an email ONLY when something important happened:
  - a holding moved >= stock_day_move_pct in its last trading day
  - the whole portfolio moved >= portfolio_day_move_pct in one day
  - an analyst upgrade or downgrade on a stock you own
  - a goal was reached (crossed since the previous day)

  python scripts/alerts.py --holdings holdings.csv            # check and email if needed
  python scripts/alerts.py --holdings holdings.csv --dry-run  # print only
"""
import argparse
import json
from datetime import datetime, timedelta, timezone

import update as u

CFG = {"stock_day_move_pct": 8, "portfolio_day_move_pct": 3, "rating_lookback_hours": 26}
CFG.update(u.CONFIG.get("alerts", {}))


def aud(n):
    return f"${n:,.0f}"


def day_change(series):
    """Last trading day's % change, or None if the price didn't change (holiday)."""
    s = series.dropna()
    if len(s) < 2 or s.iloc[-2] == 0 or s.iloc[-1] == s.iloc[-2]:
        return None
    return (s.iloc[-1] / s.iloc[-2] - 1) * 100


def find_alerts(holdings):
    prices, fx, _, _, _ = u.fetch_live(holdings)
    close = u.LAST_CLOSE
    alerts = []

    # 1) Big moves in one stock (accounts merged)
    seen = {}
    for h in holdings:
        rate = fx[h["currency"]]
        seen.setdefault(h["ticker"], {"name": h["name"], "value": 0.0})
        seen[h["ticker"]]["value"] += h["quantity"] * prices[h["ticker"]] * rate
    for t, info in seen.items():
        ch = day_change(close[t])
        if ch is not None and abs(ch) >= CFG["stock_day_move_pct"]:
            alerts.append({"type": "stock_move", "ticker": t, "name": info["name"], "pct": round(ch, 1),
                           "value_aud": round(info["value"]),
                           "message": f"{info['name']} ({t}) {'up' if ch > 0 else 'down'} {abs(ch):.1f}% in one day "
                                      f"(you hold {aud(info['value'])})"})

    # 2) Whole portfolio move (today vs previous row, prices and FX of each day)
    now_row, prev_row = close.iloc[-1], close.iloc[-2]
    def total(row):
        return sum(h["quantity"] * float(row[h["ticker"]]) *
                   (1.0 if h["currency"] == "AUD" else float(row[f"{h['currency']}AUD=X"])) for h in holdings)
    t_now, t_prev = total(now_row), total(prev_row)
    p_ch = (t_now / t_prev - 1) * 100 if t_prev else 0
    if abs(p_ch) >= CFG["portfolio_day_move_pct"]:
        alerts.append({"type": "portfolio_move", "pct": round(p_ch, 1), "change_aud": round(t_now - t_prev),
                       "message": f"Your portfolio {'rose' if p_ch > 0 else 'fell'} {abs(p_ch):.1f}% "
                                  f"({'+' if p_ch > 0 else '−'}{aud(abs(t_now - t_prev))}) in one day, now {aud(t_now)}"})

    # 3) Analyst upgrades / downgrades
    key = [f.lower() for f in u.CONFIG["key_firms"]]
    since = datetime.now(timezone.utc) - timedelta(hours=CFG["rating_lookback_hours"])
    for c in u.fetch_rating_changes(holdings, days=2):
        if c["action"] not in ("up", "down"):
            continue
        if datetime.fromisoformat(c["date"]).replace(tzinfo=timezone.utc) < since - timedelta(days=1):
            continue
        major = any(k in c["firm"].lower() for k in key)
        alerts.append({"type": "rating", "ticker": c["ticker"], "name": c["name"], "firm": c["firm"],
                       "action": c["action"], "to": c["to"], "major": major,
                       "message": f"{c['firm']}{' (major bank)' if major else ''} "
                                  f"{'upgraded' if c['action'] == 'up' else 'downgraded'} {c['name']} ({c['ticker']}) "
                                  f"to {c['to']}"})

    # 4) Goal reached
    for g in u.CONFIG["goals"]:
        if t_prev < g["amount"] <= t_now:
            alerts.append({"type": "goal", "goal": g["name"],
                           "message": f"🎉 You reached your {g['name']} goal! Portfolio is now {aud(t_now)}"})

    # Most important first: goals, whole portfolio, big moves, major-bank ratings, other ratings
    order = {"goal": 0, "portfolio_move": 1, "stock_move": 2, "rating": 3}
    alerts.sort(key=lambda a: (order[a["type"]], not a.get("major", True), -abs(a.get("pct", 0))))

    # A headline for each big mover, to explain why
    movers = [(a["ticker"], a["name"]) for a in alerts if a["type"] in ("stock_move", "rating")]
    news = u.fetch_news(list(dict.fromkeys(movers))[:6], days=3, per_ticker=1) if movers else []
    return alerts, news, round(t_now)


def build_email(alerts, news, total):
    first = alerts[0]["message"]
    subject = f"Road to 1M ALERT: {first[:70]}" + (f" (+{len(alerts) - 1} more)" if len(alerts) > 1 else "")
    items = "".join(f"<li style='margin-bottom:6px'>{a['message']}</li>" for a in alerts)
    news_html = ""
    if news:
        news_html = "<h3 style='margin:16px 0 4px'>Why it may have moved</h3><ul style='padding-left:18px'>" + "".join(
            f"<li><b>{n['ticker']}</b>: <a href='{n['link']}'>{n['title']}</a> ({n['publisher']})</li>" for n in news) + "</ul>"
    html = (f"<div style='font-family:Arial,sans-serif;font-size:15px;max-width:560px'>"
            f"<p style='color:#B3412F;font-weight:bold;margin:0'>Road to 1M alert</p>"
            f"<ul style='padding-left:18px'>{items}</ul>{news_html}"
            f"<p style='color:#5E6B66;font-size:12px'>Portfolio now {aud(total)} AUD. "
            f"For information only, not financial advice.</p></div>")
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "total_aud": total, "alerts": alerts, "news": news}
    text = (subject + "\n\n" + "\n".join("- " + a["message"] for a in alerts) +
            "\n\nALERTS_JSON_START\n" + json.dumps(payload, separators=(",", ":")) + "\nALERTS_JSON_END\n")
    return subject, html, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdings", default=str(u.ROOT / "holdings.csv"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    holdings = u.load_holdings(args.holdings)
    alerts, news, total = find_alerts(holdings)
    if not alerts:
        print(f"No alerts today. Portfolio {aud(total)}.")
        return
    subject, html, text = build_email(alerts, news, total)
    print(subject)
    for a in alerts:
        print(" -", a["message"])
    if args.dry_run:
        return
    import mailer
    mailer.send(subject, html, text)
    print("Alert email sent")
    print(f"::notice::{len(alerts)} alert(s) sent")


if __name__ == "__main__":
    main()
