# Repo Map

Folder-by-folder guide for future work.

## Root

- `main.py`: scheduler orchestration. Safe to edit for pipeline timing,
  orchestration, and digest behavior after reading tests.
- `config.py`: environment loading, rule constants, bucket targets, and SQLite
  portfolio loading. Risky because it runs database initialization at import.
- `trade.py`: disabled legacy CLI. Some helpers are still imported by the UI;
  old file-writing helpers are cleanup candidates.
- `requirements.txt`: pinned runtime/test dependencies. Avoid adding tools
  without approval.
- `pytest.ini`: pytest markers/config.
- `Dockerfile`: production image and build-time test run.
- `entrypoint.sh`: production startup, optional legacy migration bootstrap, UI
  launch, scheduler launch.
- `docker-compose.yml`: local container runtime.
- `fly.toml`: Fly.io deployment config.
- `README.md`: user-facing overview. Some operational/test-count details may
  drift; verify against code before relying on it.
- `CLAUDE.md`: compatibility pointer for Claude-specific usage. `AGENTS.md` is
  canonical for Codex.
- `finmat_agent_workflow.svg`: untracked/generated-looking diagram; currently
  references legacy storage paths.
- `.github/workflows/`: CI for `dev` and `main`.

## modules/

- `database.py`: SQLite schema and CRUD for holdings, trades, snapshots,
  watchlist tickers, and realized profit/loss/P&L aggregation. Modify for
  persistence changes.
- `portfolio.py`: pure calculations and alert-rule checks. Modify carefully;
  this is financial logic.
- `price_fetcher.py`: external market data fetches, including Yahoo stock
  quotes used by the watchlist.
- `history.py`: SQLite snapshot and performance summary logic.
- `news_sentiment.py`: news/RSS fetches and Anthropic sentiment logic.
- `decision_engine.py`: AI-generated portfolio analysis and tax-aware prompts.
- `alerts.py`: Telegram/email delivery.
- `run_logger.py`: JSONL logging library; candidate to wire in or deprecate.
- `__init__.py`: package marker.

## ui/

- `app.py`: Flask app, REST routes, Basic Auth, trade API, watchlist API, and
  dashboard portfolio response shaping.
- `static/index.html`: current single-file frontend. Safe for UI-only changes,
  but route/API changes must be coordinated with `ui/app.py`.

## portfolio/

- `local.example.py`: committed example/legacy migration seed.
- `local.py`: gitignored private local holdings file; do not commit or inspect
  unless needed and approved by the task context.
- `__init__.py`: package marker.

## scripts/

- `migrate_to_sqlite.py`: idempotent migration from legacy files to SQLite.
- `read_logs.sh`: Fly helper for JSONL log review.
- `review_logs.py`: JSONL log summarizer.
- `login.sh`: Fly/auth convenience script; inspect before use.

## tests/

Pytest suite covering the main modules and trade behavior. Prefer existing
fixtures, monkeypatch style, and deterministic mocks. Integration tests are
marked with `integration`.

## docs/

- `architecture.md`: current architecture baseline.
- `ops.md`: operational notes. Verify against code before following old steps.
- `stock-analysis-evals-approach.html`: phone-readable proposal for evaluating
  non-deterministic stock-analysis outputs.
- `playbooks/`: mode-specific workflow guides.
- `decisions/`: ADRs.
- `deprecated.md`: deprecated patterns and dead-code candidates.
- `repo-map.md`: this file.

## tasks/

Historical planning/lessons from earlier sessions. Useful context, but verify
against current code because several entries predate SQLite.

## Safe/Risky Modification Guide

Usually safe:

- Adding docs under `docs/`.
- Adding focused tests under `tests/`.
- Small UI copy/layout/API-client changes in `ui/static/index.html` that do not
  change API contracts.

Higher risk:

- Financial calculations in `modules/portfolio.py`.
- Persistence schema/CRUD in `modules/database.py`.
- Import-time behavior in `config.py`.
- Startup/deployment behavior in `Dockerfile`, `entrypoint.sh`, and `fly.toml`.
- Trade logging paths in `ui/app.py`; deprecated helpers in `trade.py`.
- AI prompts that encode Irish tax assumptions.
