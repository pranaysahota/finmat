# Finance Agent - Claude Compatibility Notes

This file is intentionally kept for Claude Code compatibility. The canonical
operating guide for coding agents is now `AGENTS.md`.

Read these first:

1. `AGENTS.md`
2. `docs/architecture.md`
3. The relevant playbook in `docs/playbooks/`
4. `docs/repo-map.md`
5. `docs/deprecated.md`

## Current Source Of Truth

The current application uses SQLite as the canonical store for holdings, trades,
and snapshots:

- Local: `data/finmat.db`
- Fly.io: `/data/finmat.db`
- Database module: `modules/database.py`
- Portfolio loader: `config.load_portfolio()`

Older instructions that describe `portfolio/local.py`, `data/trades.json`, or
`data/portfolio_history.json` as canonical runtime storage are stale. Those
files are legacy migration/fallback artifacts only.

## Claude-Specific Reminder

Before editing code, reconcile the requested work against `AGENTS.md` and the
current codebase. Do not follow older file-backed architecture descriptions if
they conflict with SQLite-backed code.

Preserve the project rules that still apply:

- Keep changes small and reviewable.
- Avoid broad rewrites unless explicitly requested.
- Do not commit `.env`, `portfolio/local.py`, `data/*.db`, `data/*.json`, or
  logs.
- Treat financial/trade data as sensitive.
- Do not change financial calculation behavior without focused tests.
- Update docs when architecture, storage, deployment, or command assumptions
  change.

