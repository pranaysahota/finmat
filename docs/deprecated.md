# Deprecated And Dead-Code Candidates

This file tracks deprecated patterns and candidates that require validation
before removal. Do not delete listed items in broad sweeps.

## Deprecated Or Legacy

| Item | Current status | Use instead | Migration notes |
| --- | --- | --- | --- |
| `portfolio/local.py` as canonical holdings storage | Legacy migration/fallback input; gitignored; may be reconstructed from secret only when legacy migration is explicitly enabled | SQLite `holdings` table via `modules/database.py` and `config.load_portfolio()` | Keep until migration and ops docs no longer require it. |
| `data/trades.json` as canonical trade log | Legacy migration/fallback input | SQLite `trades` table via `modules/database.py` | Keep migration support until production data is confirmed fully migrated and backups exist. |
| JSON snapshot file `data/portfolio_history.json` | Historical docs mention it, but current `modules/history.py` stores snapshots in SQLite | SQLite `snapshots` table | Treat any old file as migration/archive context only. |
| `trade.py` file-writing workflow | CLI entry point is disabled; legacy helper functions remain for now | Dashboard/API trade logging | Next cleanup should move shared helpers out of `trade.py`, then remove legacy file-writing helpers and tests. |

## Dead-Code Candidates To Validate

| Candidate | Evidence | Validation required before removal |
| --- | --- | --- |
| `modules/run_logger.py` integration | Module and tests exist, but `rg` shows no scheduler import/use in `main.py` | Decide whether to wire into the digest pipeline or deprecate/remove tests and scripts that assume JSONL run logs. |
| `scripts/review_logs.py` and `scripts/read_logs.sh` | They read JSONL run logs, but the logger does not appear wired into current scheduled runs | Confirm production logs and desired observability path. |
| `finmat_agent_workflow.svg` | Untracked diagram references legacy `portfolio.local.py`/`trades.json` flow | Replace/update diagram or keep outside canonical docs. |
| `.claude/worktrees/*` | Untracked local Claude worktree copy, not part of app runtime | Do not touch unless the user asks; likely local tooling state. |

## Cleanup Notes

- Use `docs/playbooks/cleanup.md` for all removals.
- Keep removals small and backed by tests/reference searches.
- Document removed user-facing paths, scripts, routes, or storage formats here.
