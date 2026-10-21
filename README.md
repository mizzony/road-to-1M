# Road to 100K

A personal portfolio agent that tracks progress to a **$100,000 AUD goal by July 2027**.

Every Monday it:
1. Values all holdings (US shares, ETFs, Thai shares, gold) in **AUD** using live prices and exchange rates
2. Forecasts when the goal will be reached under three scenarios (slow / normal / strong)
3. Finds **analyst rating changes** for US shares (JP Morgan, Goldman Sachs, Morgan Stanley and others)
4. Sends a private **weekly email** with real numbers
5. Rebuilds a **public demo dashboard** on GitHub Pages (fake data, so real money is never shown)

**Stack:** Python · yfinance · Chart.js · GitHub Actions · GitHub Pages

## Privacy design

| What | Data | Where |
|---|---|---|
| Public website | Demo data (`holdings.example.csv`) | GitHub Pages |
| Weekly email | Your real holdings | Stored only as a GitHub **secret** |

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
ticker,name,asset_class,quantity,cost_per_unit,currency
AAPL,Apple,US share,40,170,USD
VGE.AX,Vanguard Emerging Markets ETF,ETF,150,72,AUD
PTT.BK,PTT,Thai share,3000,34,THB
GC=F,Gold (troy oz),Gold,2,2300,USD
```

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
