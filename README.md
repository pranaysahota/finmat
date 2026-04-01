# finmat

A Python financial monitoring agent for an $8,000 personal investment portfolio. <br/>Tracks 9 assets across 2 active buckets, runs automated daily briefings via Telegram and weekly HTML email digests, and provides AI-powered analysis using the Anthropic API and Google Gemini — all tailored to Irish CGT rules.

---

## Agentic Workflow

```
  [Manual: Revolut purchase]
           │
           ▼
       trade.py          ← CLI: logs qty + avg_buy into portfolio/local.py
           │
           └─────────────────────────────────────────────┐
                                                         │
  ┌───────────────────────────────────────────────────┐  │
  │                  main.py (scheduler)              │  │
  │                                                   │  │
  │  ┌─ hourly ───────────────────────────────────┐   │  │
  │  │  run_price_check()                         │   │  │
  │  │   price_fetcher → portfolio → rules        │   │  │
  │  │        │                                   │   │  │
  │  │        └─ CRITICAL alert? → Telegram       │   │  │
  │  └────────────────────────────────────────────┘   │  │
  │                                                   │  │
  │  ┌─ daily 13:00 ───────────────────────────────┐  │  │
  │  │  run_daily_briefing()                       │  │  │
  │  │                                             │  │  │
  │  │   price_fetcher                             │  │  │
  │  │       │                                     │  │  │
  │  │       ▼                                     │  │  │
  │  │   portfolio.py  ← portfolio/local.py ◄──────┼──┘  │
  │  │   (calc P&L, weights, bucket drift)         │     │
  │  │       │                                     │     │
  │  │       ├──► history.py  → data/portfolio_    │     │
  │  │       │                   history.json      │     │
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
  │  ┌─ Sunday 14:30 ──────────────────────────────┐     │
  │  │  run_weekly_digest()                        │     │
  │  │   prices → sentiment → Gemini analysis      │     │
  │  │   → sell recommendations → HTML email       │     │
  │  └─────────────────────────────────────────────┘     │
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
| `run_price_check()` | Every hour | Prices → portfolio → rules → CRITICAL alert if needed. No AI, no file writes. Completes in under 10 seconds. |
| `run_daily_briefing()` | Daily 13:00 | Full pipeline: prices → portfolio → snapshot → sentiment → macro themes → AI decision → Telegram. Each step is fault-tolerant — a single failure does not abort the briefing. |
| `run_weekly_digest()` | Sunday 14:30 | Gemini-powered analysis with per-stock breakdown, sell recommendations, and Irish CGT reminder — delivered as an HTML email. |

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

### Weekly Digest (Google Gemini)
- Runs every Sunday at 14:30
- Gemini analyses each stock position using Google Search for up-to-date context
- Generates sell recommendations with explicit CGT cost calculations
- Delivered as a formatted **HTML email**

### Observability
- **JSONL run logger** (`modules/run_logger.py`) — every pipeline run is recorded with status, duration, step-level outcomes, and error details
- Logs are persisted to the `data/` volume and survive container restarts
- `scripts/read_logs.sh` — shell script for tailing and filtering raw JSONL logs
- `scripts/review_logs.py` — AI-powered log review: summarises recent runs, flags anomalies, and surfaces patterns using Claude

### Performance History
- **Append-only** daily snapshots in `data/portfolio_history.json` — never overwritten
- Tracks since-inception return, 7-day change, best/worst performers across all snapshots
- Prevents duplicate snapshots if the agent restarts mid-day
- Performance summary is included in both the daily briefing and weekly digest

### Trade Logging (Revolut Integration)
- `trade.py` is the only entry point for updating holdings — never hand-edit `portfolio/local.py`
- Interactive CLI: prompts for ticker, quantity, price paid
- Calculates new **weighted average buy price**: `(old_qty × old_avg + new_qty × price) / (old_qty + new_qty)`
- Rewrites `portfolio/local.py` using Python's `ast` module — not string replacement — to avoid corrupting comments
- Appends a permanent record to `data/trades.json`
- Shows a confirmation summary and asks for confirmation before writing anything

### Irish Tax Optimisation
- **No ETFs** — Irish exit tax (38%) + 8-year deemed disposal makes them unfavourable vs individual stocks at CGT 33%
- Individual stocks are taxed at CGT 33% on actual disposal only
- Decision engine never recommends rebalancing via disposal without explicitly noting the CGT cost
- Annual €1,270 exemption is factored into any profit-taking suggestions
- CGT payment deadlines (15 December for Jan–Nov disposals, 31 January for December) included in weekly digest

### Deployment
- **Docker** — `Dockerfile` runs unit tests at build time; build fails if any test fails
- **docker-compose** — single `docker compose up` to start, with `.env` injected and `restart: unless-stopped`
- **Fly.io** — deployed to `ams` region as a worker process; CI/CD via GitHub Actions on push to `main`
- **395 unit tests** covering all modules — all mocked, no real API calls

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
├── trade.py                     # CLI — log Revolut purchases
├── config.py                    # Settings, alert rules, bucket targets
├── modules/
│   ├── price_fetcher.py         # Yahoo Finance (+ CoinGecko when CRYPTO_ACTIVE)
│   ├── portfolio.py             # P&L, weights, bucket drift (pure calc, no I/O)
│   ├── history.py               # Append-only daily snapshots
│   ├── news_sentiment.py        # Headlines → Claude Haiku (per-ticker + macro themes)
│   ├── decision_engine.py       # Claude Sonnet daily briefing + Gemini weekly digest
│   ├── alerts.py                # Telegram message formatting + sending
│   └── run_logger.py            # JSONL run logger for pipeline observability
├── scripts/
│   ├── read_logs.sh             # Shell script for tailing/filtering JSONL logs
│   └── review_logs.py           # AI-powered log review via Claude
├── portfolio/
│   ├── local.py                 # Holdings — qty, avg_buy (gitignored)
│   └── local.example.py        # Placeholder structure (committed)
├── tests/                       # 395 unit tests — all mocked
├── tasks/
│   ├── todo.md                  # Active task plan
│   └── lessons.md               # Accumulated project lessons
└── data/
    ├── portfolio_history.json   # Daily snapshots (gitignored)
    ├── trades.json              # Trade log (gitignored)
    └── logs/                    # JSONL pipeline run logs (gitignored)
```

---

## Setup

```bash
# 1. Copy and fill in API keys
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, EMAIL_*

# 2. Set up portfolio holdings
cp portfolio/local.example.py portfolio/local.py
# Zero out all qty values, then log your first real trade:
python trade.py

# 3a. Run directly
pip install -r requirements.txt
python main.py

# 3b. Or run via Docker (recommended)
docker compose up
```

---

## API Keys Required

| Key | Service | Cost | Notes |
|-----|---------|------|-------|
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | Pay per token | Haiku for sentiment, Sonnet for daily decisions |
| `GOOGLE_API_KEY` | Google Gemini | Pay per token | Gemini for weekly digest analysis |
| `TELEGRAM_BOT_TOKEN` | Telegram BotFather | Free | Create via @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram | Free | Your personal chat ID |
| `EMAIL_*` | SMTP (weekly digest) | Free | Sender/recipient config for weekly email |
| Yahoo Finance | Stock prices | Free | No key needed |
| CoinGecko | Crypto prices | Free | No key needed (used when `CRYPTO_ACTIVE = True`) |
| Google News RSS | Headlines | Free | No key needed |

---

## Logging a Trade

After every Revolut purchase, run:

```bash
python trade.py
```

The CLI will prompt for ticker, quantity, and price paid. It calculates the new weighted average buy price, shows a confirmation summary, and updates both `portfolio/local.py` and `data/trades.json` on confirmation.
