# AGENTS.md

Primary operating guide for Codex and other coding agents working on finmat.
Read this before touching code, then read the relevant playbook under
`docs/playbooks/`.

## Project Overview

finmat is a Python 3.12 financial monitoring agent for a personal investment
portfolio. It tracks holdings and trades in SQLite, fetches live market prices,
calculates portfolio state and risk alerts, runs AI-assisted sentiment and
decision pipelines, sends Telegram/email notifications, and exposes a Flask
dashboard for portfolio review and trade logging.

Current runtime shape:

- App/runtime: Python application plus Flask dashboard.
- Scheduler: `main.py` uses `schedule` for recurring price checks and daily
  digest work.
- UI: `ui/app.py` serves a single-page dashboard from `ui/static/index.html`.
- Persistence: SQLite at `data/finmat.db` locally, or `/data/finmat.db` on
  Fly.io. Legacy `portfolio/local.py` and `data/trades.json` are migration
  inputs/fallbacks, not the canonical current store.
- External services: Yahoo Finance query endpoints, Google News RSS, Anthropic,
  Google Gemini, Telegram, SMTP/email, Fly.io.
- Deployment: Docker image deployed to Fly.io with one persistent volume and one
  machine.

## Local Setup

Use a virtual environment if possible.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env` for real integrations when running non-test workflows. Never
commit `.env`, `portfolio/local.py`, or files under `data/`.

For a fresh SQLite-only setup, do not run the legacy migration. Starting
`ui/app.py`, `main.py`, or the container imports `config.py`, which calls
`modules.database.init_db()` and creates the SQLite tables automatically. On
day 0, log the first trades through the dashboard/API and then let the scheduler
run from that SQLite state.

Run `python scripts/migrate_to_sqlite.py` only when intentionally importing
legacy `portfolio/local.py` and `data/trades.json` data into SQLite.

## Commands

Known commands:

```bash
python -m pytest tests/ -q
python -m pytest tests/ -m "not integration" -q
python main.py --once
python main.py
python ui/app.py
docker compose up
docker build .
python scripts/migrate_to_sqlite.py  # legacy migration only
./scripts/read_logs.sh --last 7
```

Formatting/linting/static analysis are not configured yet. Recommended commands
to add later, after approval:

```bash
ruff format .
ruff check .
ruff check . --select F401,F841
mypy .
vulture . --min-confidence 80
pip-audit
```

Until those tools are installed, use `python -m pytest tests/ -q` as the
baseline validation command and mark lint/type/dead-code results as "not
configured".

## Engineering Rules

- Inspect existing patterns before adding abstractions.
- Keep changes small, reviewable, and scoped to the task.
- Avoid broad rewrites unless explicitly requested.
- Do not mix feature work, refactors, cleanup, and deploy changes in one PR.
- Preserve existing external behavior unless the task is explicitly to change
  it.
- Treat financial data and trade history as sensitive. Do not print secrets,
  raw `.env`, real private holdings, or private data unnecessarily.
- Do not hand-edit `data/finmat.db`; go through app APIs, migration scripts, or
  explicit database maintenance steps.
- Do not commit generated/runtime state: `.env`, `portfolio/local.py`,
  `data/*.db`, `data/*.json`, logs, caches, virtualenvs.
- Use `pathlib` for file paths in Python changes.
- Prefer explicit error handling and deterministic tests around portfolio
  calculations, trading, persistence, and alert behavior.
- For UI work, keep `ui/app.py` as the API boundary and `ui/static/index.html`
  as the current frontend surface unless a frontend build system is deliberately
  introduced.

## Choose The Correct Playbook

- Feature or behavior addition: `docs/playbooks/build.md`
- Test-only work: `docs/playbooks/test.md`
- Internal restructuring with same behavior: `docs/playbooks/refactor.md`
- Bug investigation/fix: `docs/playbooks/debug.md`
- Release, Fly.io, Docker, secrets, runtime config: `docs/playbooks/deploy.md`
- Unused code, dependency, asset, or config removal: `docs/playbooks/cleanup.md`

## Small, Reviewable Changes

- Start with the smallest useful unit of change.
- Touch only files needed for the task.
- Add or update focused tests with behavior changes.
- Keep generated files and local runtime data out of commits.
- Explain risk and validation in the PR summary.

## Documentation Updates

Update docs in the same PR when architecture, persistence, deployment, public
commands, module ownership, or operational assumptions change.

- Update `docs/architecture.md` for component/data-flow changes.
- Update `docs/repo-map.md` for new, moved, removed, legacy, generated, or risky
  files.
- Update the relevant playbook if the workflow changes.
- Add an ADR under `docs/decisions/` for important design decisions.
- Update `docs/deprecated.md` when removing or superseding modules, files,
  patterns, APIs, or storage formats.

## Dead Code Safety

- Prefer evidence from tests, import/reference searches, runtime paths, and
  deployment scripts before removing code.
- Use `rg` first for references, then dedicated tools when configured.
- Be extra careful with externally referenced entry points, scripts, API routes,
  webhook-like endpoints, env vars, static assets, and deployment files.
- Remove dead code in small PRs with tests or characterization coverage where
  behavior assumptions could be wrong.
- Document removals or candidates in `docs/deprecated.md`.

## Definition Of Done

- The requested behavior or documentation change is complete and scoped.
- Tests relevant to the change pass, or missing validation is clearly stated.
- No unrelated behavior changes are introduced.
- Architecture/docs/playbooks are updated when assumptions change.
- Sensitive files and runtime data remain uncommitted.
- The final note includes files changed, validation run, residual risk, and any
  recommended next step.
