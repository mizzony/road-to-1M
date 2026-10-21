#!/usr/bin/env python3
"""Send the weekly report email from site/data.json.

Needs these environment variables (set them as GitHub Actions secrets):
  GMAIL_USER          your Gmail address (the sender)
  GMAIL_APP_PASSWORD  a Gmail "App password" (not your normal password)
  EMAIL_TO            where to send the report (can be the same address)

  python scripts/send_email.py            # send
  python scripts/send_email.py --preview  # just write email_preview.html
"""
import argparse
import json
import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
d = json.loads((ROOT / "site" / "data.json").read_text())


def aud(n):
    return f"${n:,.0f}"


def signed(n):
    return ("+" if n >= 0 else "−") + aud(abs(n))


def week_txt(v):
    return "" if v is None else f"{v:+.1f}% this week"


def build_html():
    green, red, muted = "#2E7D4F", "#B3412F", "#5E6B66"
    wk = d["week_change_aud"]
    wk_html = "–" if wk is None else f'<span style="color:{green if wk >= 0 else red}">{signed(wk)}</span>'
    f = d["forecast"]

    goal_rows = ""
    for g in d.get("goals", []):
        n = next((x for x in g["forecast"]["scenarios"] if x["name"] == "Normal"), g["forecast"]["scenarios"][0])
        on_track = g.get("on_track", n.get("goal_reached_month") and n["goal_reached_month"] <= g["date"][:7])
        status = ("<span style='color:#A9771F'>Reached</span>" if g["reached"] else
                  f"<span style='color:{green}'>On track</span>" if on_track else
                  f"<span style='color:{red}'>Behind</span>")
        goal_rows += (f"<tr><td style='padding:4px 12px 4px 0'><b>{g['name']}</b> by {g['date'][:7]}</td>"
                      f"<td style='padding:4px 12px 4px 0'>{g['progress_pct']}%</td>"
                      f"<td style='padding:4px 12px 4px 0'>{aud(g['forecast']['required_monthly'])}/mo needed</td>"
                      f"<td style='padding:4px 0'>{status}</td></tr>")
        sx = g.get("stretch")
        if sx and not g["reached"]:
            goal_rows += (f"<tr><td style='padding:0 12px 6px 12px;color:{muted}'>Stretch: by {sx['date'][:7]}</td><td></td>"
                          f"<td style='padding:0 12px 6px 0;color:{muted}'>{aud(sx['required_monthly'])}/mo needed</td>"
                          f"<td style='padding:0 0 6px;color:{green if sx['on_track'] else red}'>"
                          f"{'On track' if sx['on_track'] else 'Behind'}</td></tr>")

    key_changes = [c for c in d["rating_changes"] if c["key_firm"] or c["action"] in ("up", "down")]
    if key_changes:
        words = {"up": "upgraded", "down": "downgraded", "main": "kept", "init": "started", "reit": "kept"}
        changes = "".join(
            f"<li><b>{c['ticker']}</b>: {c['firm']} {words.get(c['action'], c['action'])} "
            f"{('from ' + c['from'] + ' ') if c['from'] and c['from'] != c['to'] else ''}to <b>{c['to']}</b> "
            f"<span style='color:{muted}'>({c['date']})</span></li>"
            for c in key_changes)
        changes = f"<ul style='padding-left:18px;margin:6px 0'>{changes}</ul>"
    else:
        changes = f"<p style='color:{muted};margin:6px 0'>No important rating changes this week.</p>"

    movers = sorted(d["holdings"], key=lambda h: -(h["gain_pct"] or 0))
    top = ", ".join(f"{h['ticker']} {h['gain_pct']:+.1f}%" for h in movers[:3] if h["gain_pct"] is not None)

    extra = ""
    mv = d.get("movers", {}).get("week")
    if mv:
        fmt = lambda m: f"{m['ticker']} {m['week_pct']:+.1f}%"
        extra += (f"<h3 style='margin:20px 0 4px'>This week</h3>"
                  f"<p style='margin:4px 0'><b style='color:{green}'>Up:</b> {', '.join(fmt(m) for m in mv['gainers'][:5]) or '–'}</p>"
                  f"<p style='margin:4px 0'><b style='color:{red}'>Down:</b> {', '.join(fmt(m) for m in mv['losers'][:5]) or '–'}</p>")
    if d.get("sectors"):
        extra += "<h3 style='margin:20px 0 4px'>By industry</h3><table style='border-collapse:collapse;font-size:14px'>" + "".join(
            f"<tr><td style='padding:3px 12px 3px 0'>{x['sector']}</td><td style='padding:3px 12px 3px 0'>{x['pct']}%</td>"
            f"<td style='padding:3px 0;color:{green if (x['week_pct'] or 0) >= 0 else red}'>"
            f"{week_txt(x['week_pct'])}</td></tr>"
            for x in d["sectors"][:6]) + "</table>"
    if d.get("news"):
        extra += "<h3 style='margin:20px 0 4px'>News</h3><ul style='padding-left:18px;margin:6px 0'>" + "".join(
            f"<li style='margin-bottom:4px'><b>{n['ticker']}</b>: <a href='{n['link']}' style='color:#2D6B5E'>{n['title']}</a> "
            f"<span style='color:{muted}'>({n['publisher']})</span></li>" for n in d["news"][:6]) + "</ul>"

    link = (f"<p><a href='{d['site_url']}' style='color:#2D6B5E'>Open the full dashboard →</a></p>"
            if d.get("site_url") else "")
    demo = "<p style='color:#A9771F'><b>Demo data</b> — not your real portfolio.</p>" if d["mode"] == "demo" else ""

    return f"""\
<div style="font-family:Segoe UI,Arial,sans-serif;font-size:15px;color:#15211D;max-width:560px">
  {demo}
  <p style="margin:0;color:{muted};font-size:12px;text-transform:uppercase;letter-spacing:1px">Road to 1M · {d['generated_at']}</p>
  <p style="font-size:34px;font-weight:700;margin:4px 0">{aud(d['total_aud'])} <span style="font-size:14px;color:{muted}">AUD</span></p>
  <div style="background:#DCE2DF;border-radius:6px;height:10px"><div style="background:#2D6B5E;border-radius:6px;height:10px;width:{d['progress_pct']}%"></div></div>
  <p style="margin:6px 0 16px;color:{muted}">{d['progress_pct']}% of next goal {d['goal_name']} · {aud(d['gap_aud'])} to go · {f['months_left']} months left</p>
  <table style="border-collapse:collapse">
    <tr><td style="padding:3px 16px 3px 0">This week</td><td>{wk_html}</td></tr>
    <tr><td style="padding:3px 16px 3px 0">Total gain</td><td>{signed(d['gain_aud'])} ({d['gain_pct']}%)</td></tr>
    <tr><td style="padding:3px 16px 3px 0">Needed per month</td><td>{aud(f['required_monthly'])} to hit the goal on time</td></tr>
    <tr><td style="padding:3px 16px 3px 0">Best performers</td><td>{top}</td></tr>
  </table>
  <h3 style="margin:20px 0 4px">Analyst changes</h3>
  {changes}
  {extra}
  <h3 style="margin:20px 0 4px">Goals</h3>
  <table style="border-collapse:collapse;font-size:14px">{goal_rows}</table>
  {link}
  <p style="color:{muted};font-size:12px;margin-top:24px">Analyst ratings are for information only, not advice.</p>
</div>"""


def build_dashboard():
    """The full website as ONE file with your data inside, for the email attachment."""
    page = (ROOT / "site" / "index.html").read_text()
    data_js = (ROOT / "site" / "data.js").read_text().replace("</", "<\\/")
    tag = '<script src="data.js"></script>'
    if tag not in page:
        raise SystemExit("site/index.html is missing the data.js script tag")
    from static_render import render
    page = render(page, d)  # numbers written in, so it works even without JavaScript
    return page.replace(tag, "<script>" + data_js + "</script>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()
    html = build_html()
    subject = f"Road to 1M: {aud(d['total_aud'])} ({d['progress_pct']}% of {d['goal_name']})"
    if args.preview:
        (ROOT / "email_preview.html").write_text(html)
        (ROOT / "dashboard.html").write_text(build_dashboard())
        print("Wrote email_preview.html and dashboard.html —", subject)
        return

    missing = [k for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "EMAIL_TO") if not os.environ.get(k, "").strip()]
    if missing:
        raise SystemExit(f"::error::Missing secret(s): {', '.join(missing)}. Add them in Settings > Secrets and variables > Actions.")
    user = os.environ["GMAIL_USER"].strip()
    pw = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    to = os.environ["EMAIL_TO"].strip()
    html += ("<p style='font-family:Arial,sans-serif;font-size:14px'>📎 Open <b>dashboard.html</b> "
             "(attached) in your browser to see the full dashboard with your real numbers.</p>")
    # Plain-text version: short summary + the data, so Claude can read it from Gmail
    text = (f"{subject}\n{d['progress_pct']}% of next goal {d['goal_name']}, {aud(d['gap_aud'])} to go.\n"
            "Open dashboard.html (attached) for the full dashboard.\n\n"
            "PORTFOLIO_DATA_JSON_START\n" + json.dumps(d, separators=(",", ":")) + "\nPORTFOLIO_DATA_JSON_END\n")
    body = MIMEMultipart("alternative")
    body.attach(MIMEText(text, "plain"))
    body.attach(MIMEText(html, "html"))
    msg = MIMEMultipart("mixed")
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.attach(body)
    att = MIMEApplication(build_dashboard().encode(), _subtype="html")
    att.add_header("Content-Disposition", "attachment", filename="dashboard.html")
    msg.attach(att)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise SystemExit("::error::Gmail rejected the login. Check GMAIL_USER is your full Gmail address and "
                         "GMAIL_APP_PASSWORD is a 16-letter App password (not your normal password).")
    print("Sent:", subject)


if __name__ == "__main__":
    main()
