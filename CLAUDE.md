# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Finance Agent — Project Instructions for Claude Code

Read this file in full before touching any code. Every decision here was made
deliberately. Do not deviate from these rules without being explicitly asked.

---

## What This Project Is

A Python financial monitoring agent that tracks an €8,000 personal investment
portfolio, runs daily briefings via Telegram, and provides AI-powered analysis
using the Anthropic API. The investor is based in **Ireland** and buys
manually through **Revolut** — there is no broker API integration.

---

## Architecture Overview

```
portfolio.local.py   ← holdings (qty, avg_buy) — gitignored, auto-managed
       +
price_fetcher.py     ← live prices from Yahoo Finance + CoinGecko
       ↓
portfolio.py         ← calculates current value, P&L, bucket weights
       ↓
history.py           ← saves daily snapshot → data/portfolio_history.json
       ↓
news_sentiment.py    ← fetches headlines, scores with Claude Haiku
       ↓
decision_engine.py   ← Claude Sonnet produces the daily briefing analysis
       ↓
alerts.py            ← formats and sends everything to Telegram
       ↑
main.py              ← orchestrates all of the above on a schedule
       ↑
trade.py             ← CLI tool run manually after each Revolut purchase
```

The agent has **no connection to Revolut**. It reconstructs portfolio state
entirely from `portfolio.local.py` (holdings) + live prices. The accuracy of
every calculation depends on `trade.py` being run after every purchase.

---

## Portfolio Structure

**Total capital:** $8,000
**Horizon:** 6–12 months
**Risk profile:** Moderate — Ireland CGT-optimised
**Buckets:**

| Bucket | Target | Tickers |
|--------|--------|---------|
| Diversified | 60% ($4,800) | MSFT, AAPL, JPM, JNJ, ASML, BRK.B, XOM |
| Growth | 25% ($2,000) | GOOG, NVDA |
| Crypto | 15% ($1,200) | bitcoin, ethereum |

**Why no ETFs:** Irish investors face exit tax at 38% on ETF gains plus a
mandatory deemed disposal every 8 years — even on unrealised gains. Individual
stocks and crypto are taxed at CGT 33% on actual disposal only, making them
significantly more tax-efficient for this investor.

**Benchmark:** `MSFT` is the largest position and acts as the internal
performance anchor. It is not an external index — do not attempt to fetch it
as a comparison benchmark separately from the portfolio.

**Hedging rationale per position:**
- `MSFT` — tech/cloud core, AI exposure, strong cash flows
- `AAPL` — consumer tech, defensive mega-cap
- `JPM`  — financials, outperforms when rates rise, low AI correlation
- `JNJ`  — healthcare, non-cyclical, negative correlation to tech
- `ASML` — European semiconductor equipment monopoly, genuine international exposure
- `BRK.B` — diversified conglomerate (insurance, energy, consumer), portfolio buffer
- `XOM`  — energy, strongest negative correlator to tech during inflation spikes
- `GOOG` — AI/Search/Cloud, concentrated growth bet
- `NVDA` — AI chips, highest upside and highest volatility in portfolio
- `bitcoin` — store of value, macro-uncorrelated, institutional adoption
- `ethereum` — smart contract platform, higher beta to crypto cycle than BTC

---

## File Responsibilities — Read Before Editing Anything

| File | Committed? | Managed by | Purpose |
|------|-----------|------------|---------|
| `config.py` | ✅ Yes | Human | App settings, rules, paths, bucket targets |
| `portfolio.local.py` | ❌ No | `trade.py` | Real holdings — qty and avg_buy per ticker |
| `portfolio.local.example.py` | ✅ Yes | Human | Placeholder structure to show format |
| `trade.py` | ✅ Yes | Human | CLI tool — logs Revolut purchases |
| `data/portfolio_history.json` | ❌ No | `history.py` | Daily snapshots, never overwrite |
| `data/trades.json` | ❌ No | `trade.py` | Permanent trade log |
| `.env` | ❌ No | Human | API keys — never touch in code |

**Never** read `.env` directly — always use `python-dotenv` to load it.
**Never** hand-edit `portfolio.local.py` — always route changes through `trade.py`.
**Never** overwrite `portfolio_history.json` — only append to it.

---

## Data Flow Rules

### How portfolio state is assembled
1. `config.py` imports `PORTFOLIO` from `portfolio.local.py`
2. `price_fetcher.py` fetches live prices for every ticker in `PORTFOLIO`
3. `portfolio.py` receives both and calculates the full portfolio state dict
4. Every downstream module (history, decision engine, alerts) receives this
   pre-calculated state — they do not read `portfolio.local.py` directly

### The portfolio_state dict shape
```python
{
  "total_value":    float,
  "total_cost":     float,
  "total_pnl_usd":  float,
  "total_pnl_pct":  float,
  "crypto_weight":  float,
  "bucket_values":  {"Diversified": float, "Growth": float, "Crypto": float},
  "bucket_weights": {"Diversified": float, "Growth": float, "Crypto": float},
  "holdings": {
    "MSFT": {
      "current_price": float,
      "current_value": float,
      "cost_basis":    float,
      "pnl_pct":       float,
      "pnl_usd":       float,
      "bucket":        str
    },
    # ... all other tickers
  }
}
```

### The snapshot dict shape (written by history.py)
```python
{
  "date":          "2026-02-23",
  "timestamp":     "2026-02-23T08:00:00",
  "total_value":   float,
  "total_cost":    float,
  "total_pnl_usd": float,
  "total_pnl_pct": float,
  "crypto_weight": float,
  "bucket_values": {"Diversified": float, "Growth": float, "Crypto": float},
  "holdings": {
    "MSFT": {"current_value": float, "pnl_pct": float, "pnl_usd": float},
    # ... all other tickers
  }
}
```

---

## Irish Tax Rules — Critical for the Decision Engine

The AI advisor in `decision_engine.py` must always reason within these constraints:

- **CGT rate:** 33% on gains, payable only when a position is **actually sold**
- **Annual exemption:** €1,270 of gains per year are tax-free — factor this in
  when suggesting any profit-taking
- **No ETFs:** Deliberately excluded — Irish exit tax (38%) + 8-year deemed
  disposal makes them unfavourable
- **No rebalancing via disposal** unless the tax cost is explicitly worth it —
  every disposal is a taxable event
- **Crypto swaps are taxable:** Swapping BTC → ETH triggers CGT on the BTC
  disposal even if no EUR is involved
- **Loss relief:** CGT losses on stocks can offset gains on other stocks and
  crypto — losses carry forward indefinitely
- **CGT deadlines:** 15 December for disposals Jan–Nov; 31 January for
  December disposals. Annual exemption resets 1 January.
- **EUR/USD exposure:** Portfolio is priced in USD. Gains in EUR depend on the
  exchange rate at time of disposal — always note this in briefings.

---

## trade.py Behaviour

`trade.py` is the only entry point for updating holdings. When the user runs it:

1. Prompts for: ticker, quantity bought, price paid
2. Looks up the ticker in `portfolio.local.py`
3. If found: calculates new weighted average buy price:
   ```
   new_avg = (old_qty × old_avg + new_qty × price) / (old_qty + new_qty)
   ```
4. If NOT found: asks for bucket (`Diversified / Growth / Crypto`) and type
   (`stock / crypto`), then adds it with `allocation_usd = 0`, `bucket_pct = 0`
5. Shows a confirmation summary before writing anything
6. Rewrites `portfolio.local.py` using Python's `ast` module (not string replacement)
7. Appends a trade record to `data/trades.json`

**Important:** `portfolio.local.py` qty values must be **zeroed out** before
the first `trade.py` run on any ticker. The file ships with estimated quantities
as planning placeholders — if `trade.py` runs against non-zero values, it will
calculate a wrong weighted average treating estimates as real purchases.

---

## Alert Rules

Defined in `config.py` under `RULES`:

| Rule | Threshold | Alert Level |
|------|-----------|-------------|
| `stop_loss` | pnl_pct ≤ –20% | CRITICAL |
| `take_profit` | pnl_pct ≥ +40% | HIGH |
| `crypto_weight` | crypto > 20% of portfolio | MEDIUM |
| `bucket_drift` | any bucket drifts > 5pp from target | MEDIUM |

CRITICAL alerts fire immediately from `run_price_check()` (hourly).
All other alerts are included in the daily briefing.

---

## Scheduling

| Job | Frequency | Pipeline |
|-----|-----------|---------|
| `run_price_check()` | Every hour | prices → portfolio → rules → critical alert if needed |
| `run_daily_briefing()` | Daily 08:00 | prices → portfolio → rules → snapshot → sentiment → decision → Telegram |
| `run_weekly_digest()` | Sunday 09:00 | prices → portfolio → performance summary → Telegram |

The daily briefing runs immediately on startup for testing purposes.
Each step is wrapped in `try/except` — a broken sentiment call must not
kill the entire briefing pipeline.

---

## Coding Standards

- **Python 3.11+** — use modern type hints throughout
- **pathlib** for all file paths — no raw strings
- **python-dotenv** for all env vars — never hardcode keys
- All monetary values rounded to **2 decimal places**
- Every function must have a **docstring** and **type hints**
- Never raise unhandled exceptions in pipeline modules — catch, log, return
  a safe fallback so the pipeline continues
- `portfolio.py` is **pure calculation** — no I/O, no API calls, no side effects
- `history.py` is **append-only** — never overwrite existing snapshots
- Ticker normalisation: stocks → UPPERCASE, crypto → lowercase
  (e.g. `NVDA`, `bitcoin`, `ethereum`)

---

## API Models

| Task | Model |
|------|-------|
| News sentiment scoring | `claude-haiku-4-5-20251001` — fast, cheap, runs per ticker |
| Daily decision briefing | `claude-sonnet-4-6` — full reasoning, 600 max tokens |

---

## What Not To Do

- Do not add ETF tickers to the portfolio
- Do not treat `MSFT` as an external index to fetch separately
- Do not recommend disposals in the decision engine without considering CGT
- Do not overwrite `portfolio_history.json` — always append
- Do not hand-edit `portfolio.local.py` — route through `trade.py`
- Do not read `.env` directly — always use `python-dotenv`
- Do not add `data/*.json` or `portfolio.local.py` to Git
- Do not use string replacement to rewrite `portfolio.local.py` — use `ast`
- Do not run sentiment analysis on crypto tickers — stocks only
