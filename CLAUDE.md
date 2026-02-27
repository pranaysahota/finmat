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
- `MSFT`  — tech/cloud core, AI exposure, strong cash flows
- `AAPL`  — consumer tech, defensive mega-cap
- `JPM`   — financials, outperforms when rates rise, low AI correlation
- `JNJ`   — healthcare, non-cyclical, negative correlation to tech
- `ASML`  — European semiconductor equipment monopoly, genuine international exposure
- `BRK.B` — diversified conglomerate (insurance, energy, consumer), portfolio buffer
- `XOM`   — energy, strongest negative correlator to tech during inflation spikes
- `GOOG`  — AI/Search/Cloud, concentrated growth bet
- `NVDA`  — AI chips, highest upside and highest volatility in portfolio
- `bitcoin`  — store of value, macro-uncorrelated, institutional adoption
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
| `tasks/todo.md` | ✅ Yes | Claude Code | Active task plan — updated each session |
| `tasks/lessons.md` | ✅ Yes | Claude Code | Accumulated project-specific lessons |

**Never** read `.env` directly — always use `python-dotenv` to load it.
**Never** hand-edit `portfolio.local.py` — always route changes through `trade.py`.
**Never** overwrite `portfolio_history.json` — only append to it.
**Never** print raw portfolio holdings or prices to console unnecessarily —
`portfolio.local.py` contains real financial data and must be treated as sensitive.

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

These shapes are contracts between modules. If you change one, you break
everything downstream. Do not alter them without updating every affected module.

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
- **Simplicity first:** make every change as small as possible. Touch only the
  code that needs to change. A minimal correct fix beats a clever refactor.
  Financial calculation code is especially sensitive — an elegant restructure
  that silently changes how `avg_buy` or `pnl_pct` is computed corrupts
  every downstream number and every historical snapshot.
- **Find root causes:** no temporary fixes, no workarounds that mask the real
  problem. If `trade.py` produces a wrong `new_avg`, fix the weighted average
  formula — don't patch the output.

---

## API Models

| Task | Model |
|------|-------|
| News sentiment scoring | `claude-haiku-4-5-20251001` — fast, cheap, runs per ticker |
| Daily decision briefing | `claude-sonnet-4-6` — full reasoning, 1000 max tokens |

---

## Task Management

For any multi-step change or new module build:

1. **Plan first** — write the plan to `tasks/todo.md` with checkable items
   before writing any code. For architectural changes, check in with the user
   before starting implementation.
2. **Track progress** — mark items complete as you go. Do not mark a task done
   without verifying it works. For pipeline changes, verify by running the
   affected module in isolation and confirming its output shape matches the
   data contracts defined in this file.
3. **Summarise changes** — provide a brief high-level summary after each step
   so the user knows what changed and why.
4. **Verification standard** — before marking anything complete, ask:
   - Does the output shape match the data contracts in this file?
   - Does `portfolio_history.json` remain append-only?
   - Would a silent failure here corrupt historical data?
   - Are real holdings or prices being printed to console unnecessarily?

For simple, obvious fixes (typos, log message wording, single-line changes)
skip the planning overhead and just fix it.

---

## Self-Improvement Loop

After any correction from the user, append the lesson to `tasks/lessons.md`:
- What went wrong
- The specific rule that prevents it recurring

Review `tasks/lessons.md` at the start of each session before writing any code.

**Seed lessons already learned in this project:**

1. `portfolio.local.py` qty values must be zero before first `trade.py` run —
   non-zero estimates are treated as real positions and corrupt avg_buy.
2. Bucket names are `Diversified / Growth / Crypto` — not `ETFs / Stocks / Crypto`.
   Using old names breaks `check_bucket_drift()` and all snapshot comparisons.
3. `MSFT` is a portfolio holding, not an external benchmark index.
   Do not fetch it separately as a comparison index.
4. `history.py` receives `portfolio_state` from `portfolio.py` — it does not
   read `portfolio.local.py` directly. Never add direct file reads to history.py.
5. Sentiment runs on stock tickers only — not crypto. Passing crypto tickers
   to `get_all_sentiment()` wastes API calls and returns noise.
6. `portfolio.local.py` must be rewritten using Python's `ast` module —
   never string replacement. String replacement breaks on values that appear
   in comments and produces malformed Python.

---

## Autonomous Bug Fixing

When given a bug report, a failing module, or a broken pipeline step:
- Read the error, trace it to the root cause, fix it
- Do not ask for hand-holding through stack traces
- Verify the fix works before reporting it done
- If the fix touches financial calculations, re-run the affected module and
  confirm output values are mathematically correct against a known input

If something breaks mid-fix and the path forward is unclear — stop, re-assess,
and re-plan before continuing. Do not keep pushing in the wrong direction.

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
- Do not print raw holdings quantities or avg_buy prices to console in
  non-debug contexts — this is real financial data
- Do not introduce clever abstractions or refactors that touch calculation
  logic without explicit instruction — simplicity protects correctness here