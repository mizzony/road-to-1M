"""Fill the dashboard HTML with numbers BEFORE it is sent, so it still shows
everything when JavaScript is blocked (email previews on iPhone and Gmail).
In a normal browser the page's own JavaScript redraws it with the live chart."""
import re
from datetime import date
from html import escape


def aud(n):
    return f"${n:,.0f}"


def signed(n):
    return ("+" if n > 0 else "−" if n < 0 else "") + aud(abs(n))


def month_year(iso, short=True):
    d = date.fromisoformat(iso[:10])
    return d.strftime("%b %Y" if short else "%B %Y")


def fill(page, el_id, inner, extra_attr=""):
    """Put `inner` inside the empty element with this id."""
    pat = re.compile(r'(<(\w+)([^>]*)\bid="%s"([^>]*)>)(</\2>)' % re.escape(el_id))
    m = pat.search(page)
    if not m:
        return page
    open_tag = m.group(1)
    if extra_attr:
        open_tag = open_tag[:-1] + " " + extra_attr + ">"
    return page[:m.start()] + open_tag + inner + m.group(5) + page[m.end():]


def chart_svg(d, goal):
    """Simple line chart: history + forecast scenarios + goal line."""
    W, H, L, R, T, B = 640, 280, 54, 12, 14, 30
    hist = [(h["date"], h["total_aud"]) for h in d["history"]]
    scen = goal["forecast"]["scenarios"]
    dates = [x[0] for x in hist] + [p["month"] + "-15" for s in scen for p in s["path"]] + [goal["date"]]
    ords = [date.fromisoformat(x[:10]).toordinal() for x in dates]
    x0, x1 = min(ords), max(ords)
    ymax = max([goal["amount"] * 1.1] + [v for _, v in hist] + [p["value"] for s in scen for p in s["path"]])

    def X(iso):
        return L + (date.fromisoformat(iso[:10]).toordinal() - x0) / max(1, x1 - x0) * (W - L - R)

    def Y(v):
        return T + (1 - v / ymax) * (H - T - B)

    def line(points, color, dash=""):
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in points)
        da = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<polyline points="{pts}" fill="none" style="stroke:var({color})" stroke-width="2"{da}/>'

    parts = []
    for i in range(5):  # grid + y labels
        v = ymax * i / 4
        lab = f"${v/1e6:.1f}M" if ymax >= 1e6 else f"${v/1000:.0f}k"
        parts.append(f'<line x1="{L}" x2="{W-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" style="stroke:var(--line)"/>'
                     f'<text x="{L-6}" y="{Y(v)+4:.1f}" text-anchor="end" font-size="11" style="fill:var(--muted)">{lab}</text>')
    for iso in (dates[0], hist[-1][0] if hist else dates[0], goal["date"]):
        parts.append(f'<text x="{X(iso):.1f}" y="{H-8}" text-anchor="middle" font-size="11" '
                     f'style="fill:var(--muted)">{month_year(iso)}</text>')
    parts.append(line([(dates[0], goal["amount"]), (goal["date"], goal["amount"])], "--gold"))
    colors = {"Slow": "--muted", "Normal": "--teal", "Strong": "--gold"}
    last = hist[-1] if hist else (dates[0], d["total_aud"])
    for s in scen:
        parts.append(line([last] + [(p["month"] + "-15", p["value"]) for p in s["path"]],
                          colors.get(s["name"], "--teal"), "5 4"))
    if hist:
        parts.append(line(hist, "--ink"))
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" height="100%" role="img" '
            f'aria-label="Portfolio history and forecast">{"".join(parts)}</svg>')


def render(page, d):
    goals = d["goals"]
    active = next((g for g in goals if g["name"] == d["goal_name"]), goals[0])

    page = fill(page, "updated", escape("Updated " + d["generated_at"]))
    page = fill(page, "total", aud(d["total_aud"]))
    page = fill(page, "barFill", "", f'style="width:{d["progress_pct"]}%"')
    page = fill(page, "pct", f'{d["progress_pct"]}% of {escape(d["goal_name"])}')
    page = fill(page, "goalLabel", aud(d["goal_aud"]))
    page = fill(page, "goalName", escape(d["goal_name"]))
    page = fill(page, "gap", aud(d["gap_aud"]))
    wk = d["week_change_aud"]
    page = fill(page, "week", "–" if wk is None else signed(wk),
                "" if wk is None else f'class="{"up" if wk >= 0 else "down"}"')
    gain_txt = signed(d["gain_aud"]) + (f' ({d["gain_pct"]}%)' if d["gain_pct"] is not None else "")
    page = fill(page, "gain", gain_txt, f'class="{"up" if d["gain_aud"] >= 0 else "down"}"')
    page = fill(page, "needed", aud(d["forecast"]["required_monthly"]))

    cards = []
    for g in goals:
        n = next((s for s in g["forecast"]["scenarios"] if s["name"] == "Normal"), g["forecast"]["scenarios"][0])
        on_track = n.get("goal_reached_month") and n["goal_reached_month"] <= g["date"][:7]
        st = ("done", "Reached") if g["reached"] else ("ok", "On track") if on_track else ("behind", "Behind")
        cards.append(
            f'<div class="goal-card{" active" if g is active else ""}">'
            f'<div class="top"><strong>{escape(g["name"])}</strong><span class="status {st[0]}">{st[1]}</span></div>'
            f'<div class="mini"><span style="width:{g["progress_pct"]}%"></span></div>'
            f'<div class="row"><span class="num">{g["progress_pct"]}% · {aud(g["gap_aud"])} to go</span>'
            f'<span>by {month_year(g["date"])}</span></div>'
            f'<div class="row"><span>Needed per month</span><span class="num">{aud(g["forecast"]["required_monthly"])}</span></div></div>')
    page = fill(page, "goals", "".join(cards))

    page = fill(page, "targetLabel", f'{escape(active["name"])} · {month_year(active["date"], False)}')
    colors = {"Slow": "--muted", "Normal": "--teal", "Strong": "--gold"}
    page = fill(page, "scen", "".join(
        f'<div style="--sc: var({colors.get(s["name"], "--teal")})"><strong>{s["name"]}</strong>'
        f'<span>{aud(s["monthly"])}/mo · {s["annual_return"]*100:.0f}% a year</span>'
        f'<span class="num">{aud(s["value_at_target"])} by {month_year(active["date"])}</span>'
        f'<span>{("Hits " + active["name"] + " in " + s["goal_reached"]) if s["goal_reached"] else "Not within 10 years"}</span></div>'
        for s in active["forecast"]["scenarios"]))
    # Shown only when JavaScript can't run (canvas fallback content)
    page = fill(page, "chart", chart_svg(d, active))

    verb = {"up": "Upgrade", "down": "Downgrade", "main": "Kept", "init": "New", "reit": "Kept"}
    if d["rating_changes"]:
        items = "".join(
            f'<li><span class="tk">{escape(c["ticker"])}</span>'
            f'<span class="date label">{date.fromisoformat(c["date"]).strftime("%-d %b")}</span>'
            f'<span><span class="firm">{escape(c["firm"])}</span>'
            f'{"<span class=key>Major bank</span>" if c["key_firm"] else ""}'
            f'<span style="display:block;color:var(--muted);font-size:.82rem">'
            f'{escape(c["from"]) + " → " if c["from"] and c["from"] != c["to"] else ""}{escape(c["to"])}</span></span>'
            f'<span class="chip {c["action"] if c["action"] in ("up", "down") else "same"}">'
            f'{verb.get(c["action"], escape(c["action"]))}</span></li>'
            for c in d["rating_changes"])
    else:
        items = '<li><span class="note" style="grid-column:1/-1">No rating changes for your US shares this week.</span></li>'
    page = fill(page, "changes", items)

    pal = ["--teal", "--gold", "--ink", "--muted", "--up"]
    page = fill(page, "alloc", "".join(
        f'<span style="flex:{a["pct"]};background:var({pal[i % len(pal)]})"></span>'
        for i, a in enumerate(d["allocation"])))
    page = fill(page, "legend", "".join(
        f'<span><i style="background:var({pal[i % len(pal)]})"></i>{escape(a["asset_class"])} '
        f'<span class="num">{a["pct"]}%</span> · <span class="num">{aud(a["value_aud"])}</span></span>'
        for i, a in enumerate(d["allocation"])))

    rows = []
    for h in d["holdings"]:
        sub = escape(h["ticker"] + (" · " + h["account"] if h.get("account") else ""))
        rows.append(
            f'<tr><td><strong>{escape(h["name"])}</strong><span class="sub num">{sub}</span></td>'
            f'<td>{escape(h["asset_class"])}</td>'
            f'<td class="r num">{h["price"]:,} <span class="sub">{h["currency"]}</span></td>'
            f'<td class="r num">{aud(h["value_aud"])}</td>'
            f'<td class="r num {"up" if h["gain_aud"] >= 0 else "down"}">{signed(h["gain_aud"])}'
            f'<span class="sub">{"" if h["gain_pct"] is None else str(h["gain_pct"]) + "%"}</span></td>'
            f'<td class="r num">{h["weight_pct"]}%</td></tr>')
    page = fill(page, "rows", "".join(rows))
    page = fill(page, "fx", "Exchange rates to AUD: " + " · ".join(
        f"1 {k} = {v:.4f}" for k, v in d["fx"].items() if k != "AUD"))
    if d["mode"] == "demo":
        page = page.replace('id="mode" class="badge" hidden', 'id="mode" class="badge"')
    return page
