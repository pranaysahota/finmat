# Test Plan — Integration & E2E Testing

**Runtime:** Docker
**Date:** 2026-02-27
**Scope:** Integration tests (real external APIs, isolated modules) and full E2E tests (complete pipeline in Docker)

---

## Test Layers

```
Layer 1 — Unit Tests          Already passing (302 tests, all mocked)
Layer 2 — Integration Tests   Real external APIs, module combinations, isolated steps
Layer 3 — E2E Tests           Full pipeline in Docker, real APIs, Telegram disabled
```

This plan covers **Layers 2 and 3**.

---

## Prerequisites

### Environment

Create `.env.test` alongside `.env`. This is the integration/E2E test env — it uses real API keys but targets a **test Telegram chat** (not your production chat) so no real briefings are sent to your live bot during testing.

```bash
# .env.test
ANTHROPIC_API_KEY=<same as production>
TELEGRAM_BOT_TOKEN=<same bot token, or a dedicated test bot>
TELEGRAM_CHAT_ID=<your personal Telegram user ID, not a group>
```

You can get your personal Telegram user ID by messaging @userinfobot.

### Seeded portfolio

For integration tests, `portfolio/local.py` must have at least one real position with a non-zero qty so price calculations produce meaningful output. The existing MSFT and AAPL positions are sufficient.

### Docker

```bash
docker --version    # 24+ recommended
docker compose version
```

---

## Layer 2 — Integration Tests

These test real module interactions with real external APIs but do not run the full scheduler pipeline. Each test is a short, targeted run.

---

### IT-01 — Price Fetch (Yahoo Finance + CoinGecko)

**What it tests:** `price_fetcher.get_all_prices()` against live APIs with the real PORTFOLIO config.

**Expected:**
- All 11 tickers return a non-None float price
- Stock prices are in a plausible USD range (MSFT $300–$600, NVDA $80–$200, etc.)
- Crypto prices are non-zero (BTC > $50,000, ETH > $1,000)
- No uncaught exceptions

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
prices = get_all_prices(PORTFOLIO)
missing = [t for t, p in prices.items() if p is None]
assert not missing, f'Missing prices: {missing}'
print(f'✓ All {len(prices)} prices fetched')
for ticker, price in prices.items():
    print(f'  {ticker:<10} \${price:,.2f}')
"
```

**Pass criteria:** Exits 0, all tickers have prices, output printed without errors.

**What can fail:** CoinGecko rate-limits the free tier. If BTC/ETH return None, wait 60 seconds and retry — this is a network issue, not a code bug.

---

### IT-02 — Portfolio Calculation

**What it tests:** `price_fetcher` → `portfolio.calculate_portfolio()` chain produces a correctly shaped state dict.

**Expected:**
- `total_value` is a positive float
- `holdings` contains all tickers with non-zero qty (at minimum MSFT, AAPL)
- `bucket_weights` sums to approximately 100% (within 1pp given zero-qty positions)
- `total_pnl_pct` reflects actual market movement since avg_buy

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
from modules.portfolio import calculate_portfolio, check_rules, check_bucket_drift
prices = get_all_prices(PORTFOLIO)
state = calculate_portfolio(prices)
assert state['total_value'] > 0, 'total_value must be positive'
assert 'holdings' in state
assert 'bucket_weights' in state
rules = check_rules(state)
drift = check_bucket_drift(state)
print(f'✓ Portfolio calculated — total value: \${state[\"total_value\"]:,.2f}')
print(f'  P&L: {state[\"total_pnl_pct\"]:+.2f}%')
print(f'  Crypto weight: {state[\"crypto_weight\"]:.1f}%')
print(f'  Rules triggered: {len(rules)}')
print(f'  Bucket drift alerts: {len(drift)}')
"
```

**Pass criteria:** Exits 0, `total_value > 0`, no exceptions.

---

### IT-03 — History Snapshot Write + Read

**What it tests:** `history.save_snapshot()` appends correctly and `load_history()` reads it back. Verifies the append-only contract.

**Expected:**
- A new snapshot is written to `data/portfolio_history.json`
- Re-running does NOT create a duplicate for the same date
- `load_history()` returns the same number of snapshots as written

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
from modules.portfolio import calculate_portfolio
from modules.history import save_snapshot, load_history
prices = get_all_prices(PORTFOLIO)
state = calculate_portfolio(prices)
before = len(load_history())
save_snapshot(state)
after_first = len(load_history())
save_snapshot(state)   # should not add a duplicate
after_second = len(load_history())
assert after_first == before + 1, 'First save should add exactly one snapshot'
assert after_second == after_first, 'Second save on same date should be skipped'
print(f'✓ Snapshot saved ({after_first} total, duplicate correctly skipped)')
"
```

**Pass criteria:** Exits 0, snapshot count increments by exactly 1, second call is a no-op.

**Note:** This test writes to `data/portfolio_history.json` inside the container. If you mount a volume, the snapshot persists. If using an ephemeral container (no volume), the history starts fresh each run — which is fine for this test.

---

### IT-04 — News Fetch (Google News RSS)

**What it tests:** `news_sentiment.fetch_news()` against the live Google News RSS feed.

**Expected:**
- Returns a non-empty list of headline strings for known tickers
- Each headline is a plain string (no HTML, no feedparser objects)
- Returns empty list gracefully for a nonsense query (no crash)

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from modules.news_sentiment import fetch_news
tickers = ['MSFT', 'NVDA', 'AAPL']
for ticker in tickers:
    headlines = fetch_news(f'{ticker} stock news')
    assert isinstance(headlines, list)
    print(f'  {ticker:<8} {len(headlines)} headlines')
    for h in headlines[:2]:
        print(f'    - {h[:80]}')
# Nonsense query should return empty list, not crash
result = fetch_news('xyzzy_not_a_real_thing_12345')
assert isinstance(result, list)
print('✓ News fetch passed (including graceful empty result)')
"
```

**Pass criteria:** Exits 0, at least 1 headline returned for each real ticker.

---

### IT-05 — Sentiment Scoring (Claude Haiku)

**What it tests:** `news_sentiment.score_sentiment()` against the live Anthropic API. Uses real headlines fetched in the same run.

**Expected:**
- Returns a dict with `score` (float −1.0 to 1.0), `label` (one of 5 valid values), `summary` (non-empty string)
- No crash on empty headlines (returns NEUTRAL)
- Model used is `claude-haiku-4-5-20251001`

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from modules.news_sentiment import fetch_news, score_sentiment
VALID_LABELS = {'BEARISH', 'SLIGHTLY_BEARISH', 'NEUTRAL', 'SLIGHTLY_BULLISH', 'BULLISH'}
headlines = fetch_news('MSFT stock news')
result = score_sentiment('MSFT', headlines)
assert -1.0 <= result['score'] <= 1.0, f'Score out of range: {result[\"score\"]}'
assert result['label'] in VALID_LABELS, f'Invalid label: {result[\"label\"]}'
assert result['summary'], 'Summary must not be empty'
print(f'✓ MSFT sentiment: {result[\"label\"]} ({result[\"score\"]:+.2f})')
print(f'  {result[\"summary\"]}')
# Empty headlines fallback
neutral = score_sentiment('MSFT', [])
assert neutral['label'] == 'NEUTRAL'
print('✓ Empty headlines returns NEUTRAL correctly')
"
```

**Pass criteria:** Exits 0, valid label, score in range.

---

### IT-06 — Macro Theme Sentiment (Claude Haiku)

**What it tests:** `news_sentiment.get_macro_sentiment()` runs all 4 themes and returns correctly shaped output.

**Expected:**
- Returns a dict with keys: `AI_TECH_THEME`, `SEMICONDUCTOR_THEME`, `DEFENSIVE_THEME`, `CRYPTO_THEME`
- Each theme has `score`, `label`, `summary`, `affected_tickers`
- `affected_tickers` matches the expected tickers per theme

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from modules.news_sentiment import get_macro_sentiment
EXPECTED_THEMES = {
    'AI_TECH_THEME':       ['MSFT', 'AAPL', 'GOOG', 'NVDA', 'ASML'],
    'SEMICONDUCTOR_THEME': ['NVDA', 'ASML'],
    'DEFENSIVE_THEME':     ['JPM', 'JNJ', 'XOM', 'BRK.B'],
    'CRYPTO_THEME':        ['bitcoin', 'ethereum'],
}
VALID_LABELS = {'BEARISH', 'SLIGHTLY_BEARISH', 'NEUTRAL', 'SLIGHTLY_BULLISH', 'BULLISH'}
result = get_macro_sentiment({})
assert set(result.keys()) == set(EXPECTED_THEMES.keys()), f'Missing themes: {result.keys()}'
for theme, data in result.items():
    assert data['label'] in VALID_LABELS
    assert data['affected_tickers'] == EXPECTED_THEMES[theme]
    print(f'  {theme:<25} {data[\"label\"]} ({data[\"score\"]:+.2f})')
print('✓ All 4 macro themes scored correctly')
"
```

**Pass criteria:** Exits 0, all 4 themes present with valid labels.

---

### IT-07 — Decision Engine (Claude Sonnet)

**What it tests:** `decision_engine.get_decision()` returns a correctly structured briefing string using the live API.

**Expected:**
- Response contains all 4 required sections: `MARKET MOOD`, `PORTFOLIO STATUS`, `ACTIONS REQUIRED`, `WATCH LIST`
- References at least one real ticker (MSFT, AAPL, NVDA, etc.)
- Response is under 600 tokens (enforced by `max_tokens`)
- No fallback string returned (API is live)

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
from modules.portfolio import calculate_portfolio, check_rules, check_bucket_drift
from modules.news_sentiment import get_all_sentiment, get_macro_sentiment
from modules.decision_engine import get_decision, _FALLBACK_DECISION
prices = get_all_prices(PORTFOLIO)
state = calculate_portfolio(prices)
rules = check_rules(state)
drift = check_bucket_drift(state)
stock_tickers = [t for b in PORTFOLIO.values() for t, a in b.items() if a.get('type') == 'stock']
sentiment = get_all_sentiment(stock_tickers)
macro = get_macro_sentiment(state)
decision = get_decision(state, rules, drift, macro, sentiment, {})
assert decision != _FALLBACK_DECISION, 'Got fallback — API error'
for section in ['MARKET MOOD', 'PORTFOLIO STATUS', 'ACTIONS REQUIRED', 'WATCH LIST']:
    assert section in decision, f'Missing section: {section}'
print('✓ Decision engine returned a valid briefing')
print(decision[:300] + '...')
"
```

**Pass criteria:** Exits 0, all 4 sections present, no fallback string.

---

## Layer 3 — E2E Tests

These run the full `run_daily_briefing()` and `run_price_check()` pipelines end-to-end inside Docker. Telegram send is **not tested here** — the pipeline is verified up to the point of sending, but the actual Telegram call is skipped to avoid spamming your chat.

---

### E2E-01 — Full Daily Briefing Pipeline (Telegram disabled)

**What it tests:** Every step of `run_daily_briefing()` with real APIs. The Telegram send is monkey-patched to a no-op so no message is actually sent.

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
import modules.alerts as alerts_mod
# Disable Telegram — record whether it would have been called
calls = []
alerts_mod.send_message = lambda text: calls.append(text) or True

import main
main.run_daily_briefing()

assert len(calls) == 1, f'Expected exactly 1 Telegram message, got {len(calls)}'
msg = calls[0]
for expected in ['Finance Agent', 'Daily Briefing', 'Portfolio Value', 'MARKET MOOD']:
    assert expected in msg, f'Missing in message: {expected}'
print(f'✓ Daily briefing completed — message length: {len(msg)} chars')
print(msg[:500])
"
```

**Pass criteria:** Exits 0, exactly 1 message would have been sent, contains all required sections.

---

### E2E-02 — Full Price Check Pipeline

**What it tests:** `run_price_check()` with real live prices. Verifies the hourly fast pipeline completes cleanly and only fires a Telegram message if CRITICAL rules are triggered.

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
import modules.alerts as alerts_mod
calls = []
alerts_mod.send_message = lambda text: calls.append(text) or True

import main
main.run_price_check()

# With a healthy portfolio, no CRITICAL alert is expected
# If one IS triggered, it means a real stop-loss breach — print it
if calls:
    print(f'⚠️  CRITICAL alert would have fired:')
    print(calls[0])
else:
    print('✓ Price check completed — no CRITICAL alerts (portfolio healthy)')
"
```

**Pass criteria:** Exits 0 regardless of whether a CRITICAL alert fires (the alert is legitimate if triggered).

---

### E2E-03 — Docker Build Gate

**What it tests:** The full `docker build` completes successfully, including running all 302 unit tests at build time (as defined in the Dockerfile).

**Command:**
```bash
docker build --no-cache -t finmat-test .
```

**Expected output:** The `RUN python -m pytest tests/ -v` layer passes. Build succeeds. No test failures.

**Pass criteria:** `docker build` exits 0.

**When to run:** Before any deployment, after any code change. This is the primary gate.

---

### E2E-04 — Container Startup + First Briefing

**What it tests:** `docker compose up` starts the container, `run_daily_briefing()` fires immediately on startup, and the scheduler loop begins. This is the closest to production behaviour.

**Setup:** Use `.env.test` with real keys. Telegram will send a real message to your test chat in this test only.

**Command:**
```bash
docker compose --env-file .env.test up
```

**What to watch for in the logs:**
```
🚀 Finance Agent started — 2026-02-27 08:xx:xx
📂 History: N snapshots loaded
[...] ── Daily Briefing started ──
[...] Fetching prices…
[...] Calculating portfolio…
[...] Rules checked — N triggered
[...] Saving snapshot…
[...] Loading performance summary…
[...] Running sentiment for 9 stock tickers…
[...] Running macro sentiment (4 themes)…
[...] Generating decision…
[...] Sending daily briefing…
[...] ── Daily Briefing complete ──
```

**Pass criteria:** All 8 steps logged without FAILED. A real Telegram message arrives in your test chat.

**Stop:** `Ctrl+C` or `docker compose down`.

---

### E2E-05 — Weekly Digest (Seeded History)

**What it tests:** `run_weekly_digest()` produces a formatted digest when history has at least 2 snapshots. Verifies the skip logic when history is empty.

**Docker command:**
```bash
docker compose run --rm --env-file .env.test finmat \
  python -c "
import modules.alerts as alerts_mod
calls = []
alerts_mod.send_message = lambda text: calls.append(text) or True

# Case 1: empty history — should skip silently
import modules.history as hist_mod
hist_mod.load_history = lambda: []
hist_mod.get_performance_summary = lambda: {}

import main
main.run_weekly_digest()
assert len(calls) == 0, 'Digest should be skipped with empty history'
print('✓ Weekly digest skipped correctly with empty history')

# Case 2: seeded history (2 snapshots) — should produce a digest
from unittest.mock import patch
MOCK_PERF = {
    'since_inception_pct': 3.2,
    'since_inception_usd': 256.0,
    'last_7_days_pct': 1.1,
    'best_performer':  {'ticker': 'MSFT', 'pnl_pct': 7.5},
    'worst_performer': {'ticker': 'NVDA', 'pnl_pct': -2.1},
    'total_snapshots': 2,
    'first_date': '2026-02-20',
    'latest_date': '2026-02-27',
}
with patch('main.get_performance_summary', return_value=MOCK_PERF):
    main.run_weekly_digest()
assert len(calls) == 1, f'Expected 1 digest message, got {len(calls)}'
msg = calls[0]
assert 'Weekly Digest' in msg
assert 'CGT' in msg
print('✓ Weekly digest produced correctly with seeded history')
print(msg[:300])
"
```

**Pass criteria:** Exits 0, digest skipped for empty history, digest sent for seeded history.

---

## Running All Integration Tests in Sequence

For a full integration run before deployment:

```bash
# Build first (unit tests run here)
docker build -t finmat-test .

# Then run each integration test
docker compose run --rm --env-file .env.test finmat python -c "..."  # IT-01
docker compose run --rm --env-file .env.test finmat python -c "..."  # IT-02
# ... etc.
```

Or create a shell script `tasks/run-integration-tests.sh`:

```bash
#!/bin/bash
set -e   # stop on first failure

IMAGE=finmat-test
ENV=.env.test

echo "=== IT-01: Price Fetch ==="
docker run --rm --env-file $ENV $IMAGE python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
prices = get_all_prices(PORTFOLIO)
missing = [t for t, p in prices.items() if p is None]
assert not missing, f'Missing prices: {missing}'
print(f'PASS — {len(prices)} prices fetched')
"

echo "=== IT-03: History Snapshot ==="
docker run --rm --env-file $ENV $IMAGE python -c "
from config import PORTFOLIO
from modules.price_fetcher import get_all_prices
from modules.portfolio import calculate_portfolio
from modules.history import save_snapshot, load_history
prices = get_all_prices(PORTFOLIO)
state = calculate_portfolio(prices)
before = len(load_history())
save_snapshot(state)
save_snapshot(state)
after = len(load_history())
assert after == before + 1
print('PASS — snapshot appended, duplicate skipped')
"

echo "=== E2E-01: Full Daily Briefing ==="
docker run --rm --env-file $ENV $IMAGE python -c "
import modules.alerts as a; calls=[]; a.send_message = lambda t: calls.append(t) or True
import main; main.run_daily_briefing()
assert len(calls) == 1
msg = calls[0]
for s in ['Finance Agent', 'Daily Briefing', 'MARKET MOOD']:
    assert s in msg, f'Missing: {s}'
print('PASS — full briefing pipeline completed')
"

echo "=== All integration tests passed ==="
```

---

## Known Limitations

| Limitation | Notes |
|-----------|-------|
| CoinGecko rate limits | Free tier allows ~30 req/min. IT-01 may need a retry if BTC/ETH return None. |
| Google News RSS availability | Occasionally returns empty feeds for less common queries. IT-04 may return 0 headlines — this is not a code bug. |
| Claude API latency | IT-05, IT-06, IT-07, and E2E-01 each make real API calls. Budget ~20–40 seconds per test. |
| Telegram in E2E-04 | This is the only test that sends a real Telegram message. Run it deliberately — not in automation. |
| History file state | IT-03 and E2E-01 write to `data/portfolio_history.json`. Use ephemeral containers (no volume mount) for clean runs, or inspect the file post-run to verify. |
