# Road to 1M

A personal portfolio agent that tracks progress to three goals: **$100K AUD by March 2027**, **$500K by December 2031** (stretch: 2029) and **$1M by December 2035** (stretch: 2033).

Every Monday it:
1. Values all holdings (US shares, ETFs, Thai shares, gold) in **AUD** using live prices and exchange rates
2. Forecasts when each goal will be reached under three scenarios (slow / normal / strong)
3. Finds **analyst rating changes** for US shares (JP Morgan, Goldman Sachs, Morgan Stanley and others)
4. Sends a private **weekly email** with real numbers
5. Rebuilds a **public demo dashboard** on GitHub Pages (fake data, so real money is never shown)

**Stack:** Python · yfinance · Chart.js · GitHub Actions · GitHub Pages

## Daily smart alerts

`.github/workflows/daily-alerts.yml` runs every weekday morning (Melbourne) and emails **only** when something important happened:
a holding moves 8%+ in a day, the portfolio moves 3%+ in a day, an analyst upgrade/downgrade on a stock you own, or a goal is reached.
Thresholds are in `config.json` → `alerts`. A Claude scheduled task turns the alert email into a phone notification.

## Updating holdings (locked file)

Real holdings live in `holdings.csv.age`, a locked (encrypted) file. It is safe in a public repo:
it can only be unlocked with the `HOLDINGS_KEY` secret.

```bash
python scripts/lock_holdings.py my-holdings.csv   # writes holdings.csv.age (uses the public key in holdings.pub)
git add holdings.csv.age && git commit -m "Update holdings" && git push
```

## Privacy design

| What | Data | Where |
|---|---|---|
| Public website | Demo data (`holdings.example.csv`) | GitHub Pages |
| Weekly email | Your real holdings | Locked file `holdings.csv.age`, unlocked only with the `HOLDINGS_KEY` secret |

Real holdings are never committed. `holdings.csv` is in `.gitignore`.

## Run locally

```bash
pip install -r requirements.txt
python scripts/update.py --demo                       # demo data, no internet needed
python scripts/update.py --holdings holdings.csv      # real data
python scripts/send_email.py --preview                # writes email_preview.html
cd site && python -m http.server 8000                 # open http://localhost:8000
```

## Holdings file format

```csv
account,ticker,name,asset_class,quantity,cost_per_unit,currency,total_cost,snapshot_value,snapshot_date
IG,NVDA,Nvidia,US share,22,151.81,USD,,,
Dime,TSM,TSMC ADR,US share,,,USD,647.00,664.90,2026-10-21
Thai broker,SCB.BK,SCB X,Thai share,100,137.62,THB,,,
Physical,GC=F,Physical gold,Gold,,,USD,13000,13000,2026-10-21
```

- Know the share count? Fill `quantity` and `cost_per_unit`.
- Fractional shares (only a value shown) or physical gold? Leave `quantity` blank and fill `snapshot_value` + `snapshot_date`. The script works out the quantity from that day's price.
- `total_cost` (optional) overrides quantity × cost per unit.
- Unknown tickers are skipped with a warning in the Actions log.

Tickers use Yahoo Finance codes: `.AX` = ASX, `.BK` = Thai SET, `GC=F` = gold per troy ounce (USD).

## Set up on GitHub

1. Push this repo to GitHub.
2. **Settings → Pages → Source:** GitHub Actions.
3. **Settings → Secrets and variables → Actions → New repository secret:**
   - `HOLDINGS_CSV` — paste the full contents of your real `holdings.csv`
   - `GMAIL_USER` — your Gmail address
   - `GMAIL_APP_PASSWORD` — a Gmail App Password (Google Account → Security → App passwords)
   - `EMAIL_TO` — where to send the report
4. **Actions → Weekly portfolio update → Run workflow** to test.

To update holdings later, just edit the `HOLDINGS_CSV` secret.

## Settings

Edit `config.json` to change the goal, target date, monthly deposits, expected returns, or which banks count as "major".

*Analyst ratings are shown for information only and are not financial advice.*
