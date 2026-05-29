# finmat

A Python financial monitoring agent for an $8,000 personal investment portfolio. <br/>Tracks 9 assets across 2 active buckets, runs automated price checks and daily HTML email digests, and provides AI-powered analysis using the Anthropic API and Google Gemini — all tailored to Irish CGT rules. Includes a web dashboard for live portfolio monitoring and trade logging, backed by SQLite.

---

## Agentic Workflow

```
  [Manual: Revolut purchase]
           │
           ▼
   Web Dashboard (UI)     ← log buy/sell trades via browser
           │
           ▼
       SQLite DB           ← holdings (qty, avg_buy) + trade history
           │
           └─────────────────────────────────────────────┐
                                                         │
  ┌───────────────────────────────────────────────────┐  │
  │                  main.py (scheduler)              │  │
  │                                                   │  │
  │  ┌─ daily 13:00 ──────────────────────────────┐   │  │
  │  │  run_price_check()                         │   │  │
  │  │   price_fetcher → portfolio → rules        │   │  │
  │  │        │                                   │   │  │
  │  │        └─ CRITICAL alert? → Telegram       │   │  │
  │  └────────────────────────────────────────────┘   │  │
  │                                                   │  │
  │  ┌─ daily 14:30 ───────────────────────────────┐  │  │
  │  │  run_daily_digest()                         │  │  │
  │  │                                             │  │  │
  │  │   price_fetcher                             │  │  │
  │  │       │                                     │  │  │
  │  │       ▼                                     │  │  │
  │  │   portfolio.py  ← SQLite DB ◄───────────────┼──┘  │
  │  │   (calc P&L, weights, bucket drift)         │     │
  │  │       │                                     │     │
  │  │       ├──► history.py  → SQLite snapshots   │     │
  │  │       │                                     │     │
  │  │       ├──► news_sentiment.py                │     │
  │  │       │    (Claude Haiku — per ticker       │     │
  │  │       │     + macro themes)                 │     │
  │  │       │                                     │     │
  │  │       └──► decision_engine.py               │     │
  │  │            (Claude Sonnet — full briefing)  │     │
  │  │                │                            │     │
  │  │                ▼                            │     │
  │  │           alerts.py → Telegram              │     │
  │  └─────────────────────────────────────────────┘     │
  │                                                      │
  │  Dashboard endpoint /api/digest can trigger the      │
  │  same digest pipeline asynchronously.                │
  └──────────────────────────────────────────────────────┘
```

---

## Features

### Portfolio Tracking
- **9 assets across 2 buckets** — Diversified (60%), Growth (25%) — crypto paused (`CRYPTO_ACTIVE = False`)
- **Live prices** fetched from Yahoo Finance (stocks) — no API key required
- **Per-position P&L** — current value, cost basis, unrealised gain/loss in USD and %
- **Bucket weight tracking** — actual vs target allocation per bucket
- **Weighted average buy price** — automatically recalculated each time a trade is logged

### Alert System
- **CRITICAL alerts** fire immediately via Telegram when triggered during the hourly price check
- **Risk proximity flags** embedded in Claude's context: stop-loss proximity (P&L ≤ −12%), take-profit proximity (P&L ≥ +32%)
- All alert levels and thresholds are configurable in `config.py` under `RULES`
- **Telegram message splitting** — messages exceeding Telegram's 4096-character limit are automatically split and sent in sequence

| Condition | Level | Fires in |
|-----------|-------|----------|
| Position P&L ≤ −20% | CRITICAL | Hourly check |
| Position P&L ≥ +40% | HIGH | Daily briefing |
| Any bucket drifts > 5pp from target | MEDIUM | Daily briefing |

### Three-Tier Scheduled Pipeline

| Job | Schedule | What it does |
|-----|----------|-------------|
| `run_price_check()` | Daily 13:00 | Prices → portfolio → rules → CRITICAL alert if needed. No AI, no file writes. Completes quickly. |
| `run_daily_digest()` | Daily 14:30 | Full pipeline: prices → portfolio → SQLite snapshot → sentiment → macro themes → Gemini analysis → sell recommendations → HTML email. Each step is fault-tolerant — a single failure does not abort the digest. |

### AI Sentiment Analysis (Claude Haiku)
- **Per-ticker sentiment** — Google News RSS headlines scored for each stock position
- **Macro cross-position themes** scored independently:
  - `AI_TECH_THEME` — covers MSFT, AAPL, GOOG, NVDA, ASML
  - `SEMICONDUCTOR_THEME` — covers NVDA, ASML
  - `DEFENSIVE_THEME` — covers JPM, JNJ, XOM, BRK.B
- **DOUBLE SIGNAL detection** — flags positions that are bearish on both their individual ticker sentiment and a macro theme simultaneously
- Sentiment runs on stocks only — not on crypto tickers (even when crypto is active)

### AI Decision Engine (Claude Sonnet)
- Receives the full context block: portfolio snapshot, bucket breakdown, holdings with risk flags, triggered rules, macro themes with portfolio weight affected, per-ticker sentiment, and performance history
- System prompt is explicitly aware of the **hedging rationale** — JPM, JNJ, XOM, BRK.B are deliberate hedges against tech/AI weakness
- All recommendations are **Irish CGT-aware**: 33% CGT on disposal, €1,270 annual exemption, no ETF rebalancing advice, crypto swap tax treatment
- Response is structured: MARKET MOOD → PORTFOLIO STATUS → WATCH LIST. When a CRITICAL or HIGH alert triggers, a CGT IMPACT section is appended with the Irish tax calculation for each flagged position

### Daily Email Digest (Google Gemini)
- Runs every day at 14:30
- Gemini analyses each stock position using Google Search for up-to-date context
- Generates sell recommendations with explicit CGT cost calculations
- Delivered as a formatted **HTML email**

### Observability
- Runtime progress and failures are currently printed to process logs
- `modules/run_logger.py` and `scripts/review_logs.py` exist for JSONL workflow logging/review, but the logger does not appear to be wired into `main.py` yet
- On Fly.io, use `fly logs --app finmat` as the current operational log source

### Performance History
- **Append-only** daily snapshots in the SQLite `snapshots` table
- Holdings and trade history persisted in **SQLite** (`data/finmat.db`)
- Tracks since-inception return, 7-day change, best/worst performers across all snapshots
- Prevents duplicate snapshots if the agent restarts mid-day
- Performance summary is included in the daily digest

### Web Dashboard
- **Live portfolio view** — summary cards, per-holding table with sortable columns (Stock, Value, P&L), bucket allocation and holdings breakdown charts
- **Trade logging** — buy and sell trades submitted via the browser, with live total calculation and validation
- **Recent transactions** — last 5 trades displayed in a scrollable table
- **Basic Auth** — protected by `DASHBOARD_USER` / `DASHBOARD_PASSWORD` environment variables
- Served by Flask (`ui/app.py`) and exposed via Fly.io HTTP service

### Trade Logging
- Trades are logged via the **web dashboard** — buy or sell, with ticker, quantity, and price
- Calculates new **weighted average buy price**: `(old_qty × old_avg + new_qty × price) / (old_qty + new_qty)`
- All holdings and trades are persisted in **SQLite** (`data/finmat.db`) via `modules/database.py`
- `trade.py` is a disabled legacy CLI; use the dashboard or `POST /api/trade`

### Irish Tax Optimisation
- **No ETFs** — Irish exit tax (38%) + 8-year deemed disposal makes them unfavourable vs individual stocks at CGT 33%
- Individual stocks are taxed at CGT 33% on actual disposal only
- Decision engine never recommends rebalancing via disposal without explicitly noting the CGT cost
- Annual €1,270 exemption is factored into any profit-taking suggestions
- CGT payment deadlines (15 December for Jan–Nov disposals, 31 January for December) included in the daily digest

### Deployment
- **Docker** — `Dockerfile` runs unit tests at build time; build fails if any test fails
- **docker-compose** — single `docker compose up` to start, with `.env` injected and `restart: unless-stopped`
- **Fly.io** — deployed to `ams` region with Flask HTTP service and scheduler in one container; CI/CD via GitHub Actions on push to `main`
- **325 passing tests, 4 skipped** in the current local pytest run

---

## Portfolio

**$8,000 across 2 active buckets — Ireland CGT-optimised (individual stocks, no ETFs)**

| Bucket | Target | Holdings | Rationale |
|--------|--------|----------|-----------|
| Diversified | 60% | MSFT, AAPL, JPM, JNJ, ASML, BRK.B, XOM | Multi-sector hedge: tech, financials, healthcare, energy, conglomerate |
| Growth | 25% | GOOG, NVDA | High-conviction AI/tech plays |

> Crypto bucket is currently paused (`CRYPTO_ACTIVE = False` in `config.py`). Re-enable to resume BTC/ETH tracking and crypto-specific sentiment.

**Hedging logic:** JPM, JNJ, XOM, and BRK.B are deliberate negative correlators to tech. When AI sentiment is bearish, these positions are expected to offset losses — the agent reasons about this explicitly before recommending action.

---

## Project Structure

```
finmat/
├── main.py                      # Scheduler — orchestrates all pipelines
├── trade.py                     # Disabled legacy CLI; helpers still imported by UI
├── config.py                    # Settings, alert rules, bucket targets
├── modules/
│   ├── price_fetcher.py         # Yahoo Finance (+ CoinGecko when CRYPTO_ACTIVE)
│   ├── portfolio.py             # P&L, weights, bucket drift (pure calc, no I/O)
│   ├── history.py               # SQLite daily snapshots
│   ├── news_sentiment.py        # Headlines → Claude Haiku (per-ticker + macro themes)
│   ├── decision_engine.py       # Claude/Gemini analysis and recommendations
│   ├── alerts.py                # Telegram message formatting + sending
│   ├── database.py              # SQLite persistence — holdings + trades
│   └── run_logger.py            # JSONL run logger candidate (not currently wired)
├── ui/
│   ├── app.py                   # Flask REST API + Basic Auth
│   └── static/index.html        # Single-page dashboard (portfolio, charts, trade form)
├── scripts/
│   ├── read_logs.sh             # Shell script for tailing/filtering JSONL logs
│   └── review_logs.py           # AI-powered log review via Claude
├── tests/                       # Unit tests — all mocked
├── tasks/
│   ├── todo.md                  # Active task plan
│   └── lessons.md               # Accumulated project lessons
└── data/
    └── finmat.db                # SQLite database — holdings, trades, snapshots (gitignored)
```

---

## Setup

```bash
# 1. Copy and fill in API keys
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
#          DASHBOARD_USER, DASHBOARD_PASSWORD, EMAIL_*

# 2. Install dependencies
pip install -r requirements.txt

# 3a. Run the scheduler
python main.py

# 3b. Run the web dashboard (port 5001)
python ui/app.py
# Then log your first trade via the dashboard at http://localhost:5001

# 3c. Or run via Docker (recommended)
docker compose up
```

---

## API Keys Required

| Key | Service | Cost | Notes |
|-----|---------|------|-------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | Pay per token | Haiku for sentiment, Sonnet for daily decisions |
| `GOOGLE_API_KEY` | Google Gemini | Pay per token | Gemini for daily digest analysis |
| `TELEGRAM_BOT_TOKEN` | Telegram BotFather | Free | Create via @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram | Free | Your personal chat ID |
| `DASHBOARD_USER` | Web dashboard | — | Basic Auth username (default: `finmat`) |
| `DASHBOARD_PASSWORD` | Web dashboard | — | Basic Auth password (auth disabled if unset) |
| `EMAIL_*` | SMTP (daily digest) | Free | Sender/recipient config for digest email |
| Yahoo Finance | Stock prices | Free | No key needed |
| CoinGecko | Crypto prices | Free | No key needed (used when `CRYPTO_ACTIVE = True`) |
| Google News RSS | Headlines | Free | No key needed |

---

## Logging a Trade

After every Revolut purchase, log the trade via the **web dashboard**:

1. Open the dashboard at your deployed URL (or `http://localhost:5001` locally)
2. Use the **Log a Trade** form — select buy/sell, enter ticker, quantity, and price
3. The trade is persisted to SQLite and the portfolio updates immediately

The legacy `trade.py` CLI is disabled so it cannot write stale file-backed
portfolio data. Running it prints guidance for the dashboard and API.
