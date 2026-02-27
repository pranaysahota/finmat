# finmat

A Python financial monitoring agent for an $8,000 personal investment portfolio. <br/>Tracks 11 assets across 3 buckets, runs automated daily briefings via Telegram, and provides AI-powered analysis using the Anthropic API — all tailored to Irish CGT rules.

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
  │  ┌─ daily 08:00 ───────────────────────────────┐  │  │
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
  │  │       │     + 4 macro themes)               │     │
  │  │       │                                     │     │
  │  │       └──► decision_engine.py               │     │
  │  │            (Claude Sonnet — full briefing)  │     │
  │  │                │                            │     │
  │  │                ▼                            │     │
  │  │           alerts.py → Telegram              │     │
  │  └─────────────────────────────────────────────┘     │
  │                                                      │
  │  ┌─ Sunday 09:00 ──────────────────────────────┐     │
  │  │  run_weekly_digest()                        │     │
  │  │   prices → portfolio → summary → Telegram   │     │
  │  └─────────────────────────────────────────────┘     │
  └──────────────────────────────────────────────────────┘
```

---

## Features

### Portfolio Tracking
- **11 assets across 3 buckets** — Diversified (60%), Growth (25%), Crypto (15%)
- **Live prices** fetched from Yahoo Finance (stocks) and CoinGecko (crypto) — no API key required for either
- **Per-position P&L** — current value, cost basis, unrealised gain/loss in USD and %
- **Bucket weight tracking** — actual vs target allocation per bucket
- **Weighted average buy price** — automatically recalculated each time a trade is logged

### Alert System
- **CRITICAL alerts** fire immediately via Telegram when triggered during the hourly price check
- **Risk proximity flags** embedded in Claude's context: stop-loss proximity (P&L ≤ −12%), take-profit proximity (P&L ≥ +32%)
- All alert levels and thresholds are configurable in `config.py` under `RULES`

| Condition | Level | Fires in |
|-----------|-------|----------|
| Position P&L ≤ −20% | CRITICAL | Hourly check |
| Position P&L ≥ +40% | HIGH | Daily briefing |
| Crypto weight > 20% of portfolio | MEDIUM | Daily briefing |
| Any bucket drifts > 5pp from target | MEDIUM | Daily briefing |

### Three-Tier Scheduled Pipeline

| Job | Schedule | What it does |
|-----|----------|-------------|
| `run_price_check()` | Every hour | Prices → portfolio → rules → CRITICAL alert if needed. No AI, no file writes. Completes in under 10 seconds. |
| `run_daily_briefing()` | Daily 08:00 | Full pipeline: prices → portfolio → snapshot → sentiment → macro themes → AI decision → Telegram. Each step is fault-tolerant — a single failure does not abort the briefing. |
| `run_weekly_digest()` | Sunday 09:00 | Performance summary with best/worst performers and Irish CGT reminder. |

### AI Sentiment Analysis (Claude Haiku)
- **Per-ticker sentiment** — Google News RSS headlines scored for each stock position
- **4 macro cross-position themes** scored independently:
  - `AI_TECH_THEME` — covers MSFT, AAPL, GOOG, NVDA, ASML
  - `SEMICONDUCTOR_THEME` — covers NVDA, ASML
  - `DEFENSIVE_THEME` — covers JPM, JNJ, XOM, BRK.B
  - `CRYPTO_THEME` — covers BTC, ETH
- **DOUBLE SIGNAL detection** — flags positions that are bearish on both their individual ticker sentiment and a macro theme simultaneously
- Sentiment runs on stocks only during the daily briefing — not on crypto tickers, not during the hourly price check

### AI Decision Engine (Claude Sonnet)
- Receives the full context block: portfolio snapshot, bucket breakdown, holdings with risk flags, triggered rules, macro themes with portfolio weight affected, per-ticker sentiment, and performance history
- System prompt is explicitly aware of the **hedging rationale** — JPM, JNJ, XOM, BRK.B are deliberate hedges against tech/AI weakness. A bearish AI theme does not automatically warrant action if the defensive positions are offsetting
- All recommendations are **Irish CGT-aware**: 33% CGT on disposal, €1,270 annual exemption, no ETF rebalancing advice, crypto swap tax treatment
- Response is structured: MARKET MOOD → PORTFOLIO STATUS → ACTIONS REQUIRED → WATCH LIST

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
- Individual stocks and crypto are taxed at CGT 33% on actual disposal only
- Decision engine never recommends rebalancing via disposal without explicitly noting the CGT cost
- Crypto-to-crypto swaps (BTC → ETH) are correctly treated as taxable events
- Annual €1,270 exemption is factored into any profit-taking suggestions
- CGT payment deadlines (15 December for Jan–Nov disposals, 31 January for December) included in weekly digest

### Deployment
- **Docker** — `Dockerfile` runs unit tests at build time; build fails if any test fails
- **docker-compose** — single `docker compose up` to start, with `.env` injected and `restart: unless-stopped`
- **302 unit tests** covering all modules — all mocked, no real API calls

---

## Portfolio

**€8,000 across 3 buckets — Ireland CGT-optimised (individual stocks + crypto, no ETFs)**

| Bucket | Target | Holdings | Rationale |
|--------|--------|----------|-----------|
| Diversified | 60% | MSFT, AAPL, JPM, JNJ, ASML, BRK.B, XOM | Multi-sector hedge: tech, financials, healthcare, energy, conglomerate |
| Growth | 25% | GOOG, NVDA | High-conviction AI/tech plays |
| Crypto | 15% | BTC, ETH | Macro-uncorrelated store of value + smart contract exposure |

**Hedging logic:** JPM, JNJ, XOM, and BRK.B are deliberate negative correlators to tech. When AI sentiment is bearish, these positions are expected to offset losses — the agent reasons about this explicitly before recommending action.

---

## Project Structure

```
finmat/
├── main.py                      # Scheduler — orchestrates all pipelines
├── trade.py                     # CLI — log Revolut purchases
├── config.py                    # Settings, alert rules, bucket targets
├── modules/
│   ├── price_fetcher.py         # Yahoo Finance + CoinGecko
│   ├── portfolio.py             # P&L, weights, bucket drift (pure calc, no I/O)
│   ├── history.py               # Append-only daily snapshots
│   ├── news_sentiment.py        # Headlines → Claude Haiku (per-ticker + macro themes)
│   ├── decision_engine.py       # Claude Sonnet daily briefing
│   └── alerts.py                # Telegram message formatting + sending
├── portfolio/
│   ├── local.py                 # Holdings — qty, avg_buy (gitignored)
│   └── local.example.py         # Placeholder structure (committed)
├── tests/                       # 302 unit tests — all mocked
├── tasks/
│   ├── todo.md                  # Active task plan
│   └── lessons.md               # Accumulated project lessons
└── data/
    ├── portfolio_history.json   # Daily snapshots (gitignored)
    └── trades.json              # Trade log (gitignored)
```

---

## Setup

```bash
# 1. Copy and fill in API keys
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

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
| `ANTHROPIC_API_KEY` | Anthropic (Claude) | Pay per token | Haiku for sentiment, Sonnet for decisions |
| `TELEGRAM_BOT_TOKEN` | Telegram BotFather | Free | Create via @BotFather |
| `TELEGRAM_CHAT_ID` | Telegram | Free | Your personal chat ID |
| Yahoo Finance | Stock prices | Free | No key needed |
| CoinGecko | Crypto prices | Free | No key needed |
| Google News RSS | Headlines | Free | No key needed |

---

## Logging a Trade

After every Revolut purchase, run:

```bash
python trade.py
```

The CLI will prompt for ticker, quantity, and price paid. It calculates the new weighted average buy price, shows a confirmation summary, and updates both `portfolio/local.py` and `data/trades.json` on confirmation.
