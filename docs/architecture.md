# Architecture

This document describes the current codebase baseline. Older docs may mention
JSON or `portfolio/local.py` as canonical storage; the current app uses SQLite
for holdings, trades, and snapshots.

## Main Components

- `main.py`: scheduler entry point. Runs market-hours price checks, the daily
  Growth plus watchlist briefing, and the Sunday all-stock briefing.
- `ui/app.py`: Flask REST API and dashboard server. Provides portfolio views,
  trade logging, watchlist management, recent trades, and manual digest
  triggering.
- `modules/database.py`: SQLite persistence layer for holdings, trades,
  watchlist tickers, migrations, and snapshots.
- `modules/price_fetcher.py`: market price retrieval from Yahoo Finance and,
  when crypto is enabled, CoinGecko-style crypto endpoints. The dashboard
  watchlist also uses Yahoo chart metadata for current price and previous close.
- `modules/portfolio.py`: pure portfolio calculations and risk rule checks.
- `modules/history.py`: snapshot persistence and performance summaries backed by
  SQLite.
- `modules/news_sentiment.py`: RSS/news collection and Anthropic-powered
  sentiment scoring.
- `modules/decision_engine.py`: Anthropic/Gemini-assisted analysis, sell
  recommendations, and tax-aware decision content.
- `modules/alerts.py`: Telegram and email delivery.
- `modules/run_logger.py`: JSONL workflow logger. It is tested, but current
  `main.py` does not appear to instantiate it.
- `trade.py`: disabled legacy CLI. It still contains helper functions imported
  by the UI, but running it no longer writes `portfolio/local.py` or
  `data/trades.json`.
- `scripts/migrate_to_sqlite.py`: one-time/idempotent migration from legacy file
  storage into SQLite. Not required for a fresh SQLite-only setup.

## Data Flow

Dashboard trade flow:

1. User submits a trade in `ui/static/index.html`.
2. `ui/app.py` validates the request.
3. `modules.database.upsert_holding()` and `insert_trade()` update SQLite.
4. Future calls to `config.load_portfolio()` read holdings from SQLite.

Dashboard watchlist flow:

1. User adds or removes a ticker in `ui/static/index.html`.
2. `ui/app.py` validates and normalizes stock tickers through
   `modules.database` watchlist helpers.
3. `GET /api/watchlist` reads the persisted ticker list and fetches current
   price plus previous close from Yahoo Finance.
4. Quote failures are returned as unavailable row values without removing the
   ticker.

Scheduled briefing flow:

1. `main.py` loads holdings through `config.load_portfolio()`.
2. `modules.price_fetcher.get_all_prices()` fetches live prices.
3. `modules.portfolio.calculate_portfolio()` builds the portfolio state.
4. `modules.history.save_snapshot()` writes one snapshot per day to SQLite.
5. `main.py` scopes the briefing: daily uses held Growth stocks plus
   `modules.database.get_watchlist_tickers()`, while weekly uses all held stock
   positions.
6. `modules.news_sentiment` collects ticker and macro sentiment for that scope.
7. `modules.decision_engine` builds AI analysis and sell recommendations.
   Watchlist tickers appear in analysis only, not sell recommendations.
8. `modules.alerts.send_daily_email()` sends the HTML briefing.

Price-check flow:

1. `main.py` checks US market hours.
2. It loads SQLite holdings, fetches prices, calculates state, and checks rules.
3. Only CRITICAL alerts are sent immediately through Telegram.

## Entry Points

- `python main.py`: long-running scheduler.
- `python main.py --once`: run one daily Growth plus watchlist briefing and exit.
- `python ui/app.py`: local Flask dashboard on port 5001.
- `docker compose up`: build/run the container locally.
- `Dockerfile`/`entrypoint.sh`: production container startup.
- `python trade.py`: disabled legacy CLI that prints dashboard/API guidance.
- `python scripts/migrate_to_sqlite.py`: legacy idempotent migration/bootstrap
  only when importing file-backed data.

## Storage And Database Assumptions

- SQLite is the canonical current store: `data/finmat.db` locally and
  `/data/finmat.db` on Fly.io.
- Tables are created in `modules/database.init_db()` at import/startup time, so
  a fresh empty SQLite database is a valid day-0 state.
- The dashboard stores watchlist stock tickers in SQLite. Watchlist rows are
  independent from portfolio holdings and trades.
- Realized profit, loss, and net P&L are derived from `gross_pnl` on sell
  trades only. Open-position P&L remains the portfolio calculation output from
  current value minus cost basis.
- SQLite WAL mode and foreign keys are enabled per connection.
- Runtime files under `data/` are gitignored and should not be committed.
- `portfolio/local.py` and `data/trades.json` are legacy migration artifacts.
  They still matter to migration workflows, but should not be treated as
  canonical current runtime state.

## External Integrations

- Anthropic API: sentiment and decision support.
- Google Gemini API: digest/sell recommendation analysis.
- Yahoo Finance: stock price fetches without an API key.
- Google News RSS and other RSS feeds: news inputs.
- Telegram Bot API: critical alerts.
- SMTP/email: daily digest delivery.
- Fly.io: production hosting, volume, logs, and deployment.

## Boundaries To Respect

- Keep `modules/portfolio.py` calculation-oriented and free of network/database
  I/O.
- Keep SQLite access concentrated in `modules/database.py` and callers that are
  explicit persistence boundaries.
- Keep route handlers in `ui/app.py` thin; share trade/calculation logic when
  refactoring becomes safe.
- Treat `config.py` as application configuration and portfolio-loading glue, not
  a general service container.
- Do not change portfolio-state dict shape without updating all downstream
  consumers and tests.

## Known Weak Areas

- Older task docs may still mention JSON-era workflows.
- `trade.py` still contains unused legacy file-writing helper functions, though
  the CLI entry point is disabled.
- `modules/run_logger.py` is tested but appears not wired into the scheduler.
- `docs/ops.md` and older task docs may contain pre-SQLite operational steps.
- No formatter, linter, static type checker, dependency scanner, or dead-code
  detector is configured.
- The README currently claims more tests than are present in the latest local
  run.
- Docker build runs the whole test suite, which is safe but can make deploy
  feedback slower.
