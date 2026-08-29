# ADR 0001: Current Architecture Baseline

## Status

Accepted as current baseline.

## Context

finmat was built quickly as a personal finance monitoring agent. It now combines
scheduled portfolio analysis, a Flask dashboard, SQLite persistence, external
market/news/AI integrations, and Fly.io deployment. Some documentation still
reflects an older file-backed design using `portfolio/local.py`,
`data/trades.json`, and `data/portfolio_history.json`.

This ADR records the architecture as it exists now so future changes can be
made safely and deliberately.

## Current Design

- Python 3.12 application.
- `main.py` runs scheduled price checks, daily Growth plus watchlist briefings,
  and Sunday all-stock briefings.
- `ui/app.py` runs a Flask dashboard/API on port 5001.
- SQLite is the canonical persistence layer for holdings, trades, and snapshots.
- Fresh day-0 SQLite setup is valid without legacy migration; startup creates
  tables and trades can be logged manually through the dashboard/API.
- `modules/database.py` creates and accesses the database directly.
- `config.load_portfolio()` reads current holdings from SQLite for each
  pipeline run.
- `modules/portfolio.py` calculates portfolio state from a provided prices dict
  and portfolio dict.
- Legacy file-backed holdings/trades remain for migration/fallback paths,
  especially `trade.py` and `scripts/migrate_to_sqlite.py`; the deployed
  entrypoint treats that migration as opt-in.
- Docker and Fly.io provide deployment, with persistent data mounted at `/data`.

## Consequences

- Future work should treat SQLite as the source of truth.
- Legacy JSON/Python-file paths need careful deprecation rather than abrupt
  removal.
- Tests should increasingly characterize SQLite-backed trade and snapshot
  behavior.
- Operational docs must be kept in sync with `/data/finmat.db` and the Flask
  dashboard runtime.
- Running more than one production machine can duplicate scheduled jobs.

## Known Tradeoffs

- Importing `config.py` initializes the database, which is convenient but makes
  imports side-effectful.
- SQLite keeps deployment simple but needs care around backups, migrations, and
  single-instance scheduling.
- `trade.py` is disabled as a CLI, but still contains legacy helper functions.
- The Flask dashboard and scheduler run in the same container via
  `entrypoint.sh`, keeping deployment simple while coupling their lifecycles.
- No formal lint/type/dead-code tooling is configured yet.

## Future Migration Candidates

- Move shared helpers out of `trade.py`, then remove the disabled legacy CLI and
  file-writing helpers.
- Wire `modules/run_logger.py` into `main.py` or remove the unused logger path.
- Add a small migration framework beyond the current migrations table.
- Add Ruff formatting/linting and a dead-code detector such as Vulture.
- Add backup/restore documentation for `/data/finmat.db`.
- Separate scheduler and web processes only if operational complexity is worth
  it.
