# Finmat Operations Guide

Operational notes for the current SQLite-backed Fly.io deployment.

## Runtime Overview

- App: `finmat`
- Platform: Fly.io
- Region: `ams`
- Container: Python 3.12 Docker image
- HTTP service: Flask dashboard on port 5001
- Scheduler: `main.py` runs in the same container
- Persistent volume: mounted at `/data`
- Canonical database: `/data/finmat.db`
- Process count: keep exactly one machine running to avoid duplicate scheduled
  jobs and notifications

## Common Fly Commands

```bash
fly status --app finmat
fly machines list --app finmat
fly logs --app finmat
fly secrets list --app finmat
fly volumes list --app finmat
fly ssh console --app finmat
```

Run a one-off digest on the machine:

```bash
fly ssh console --app finmat --command "cd /app && python main.py --once"
```

Inspect the SQLite database on the machine:

```bash
fly ssh console --app finmat --command "sqlite3 /data/finmat.db '.tables'"
fly ssh console --app finmat --command "sqlite3 /data/finmat.db 'select count(*) from trades;'"
```

## Deployment

CI deploys on push to `main` after tests and Docker build pass. Manual deploy:

```bash
fly deploy --app finmat
```

Local validation before deploy:

```bash
python -m pytest tests/ -q
docker build .
```

## Secrets

Required integrations are loaded from environment variables/Fly secrets. Names
include:

- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DASHBOARD_USER`
- `DASHBOARD_PASSWORD`
- `EMAIL_*`

`PORTFOLIO_LOCAL_PY` may still exist for legacy migration/bootstrap support, but
it is not the canonical current storage path. Legacy migration is opt-in at
container startup with `RUN_SQLITE_MIGRATION=1`.

## Persistent Data

Current:

- `/data/finmat.db`: SQLite holdings, trades, snapshots, migration records.
- `/data/logs/`: JSONL logs if/when `modules/run_logger.py` is wired in.

Legacy/migration context:

- `/app/portfolio/local.py`
- `/data/trades.json`
- `/data/portfolio_history.json`

Do not assume legacy files are up to date. Check SQLite first.

## Backup And Restore Notes

Recommended backup command when authorized:

```bash
fly ssh console --app finmat --command "sqlite3 /data/finmat.db '.backup /data/finmat-backup.db'"
```

Then copy the backup out using an approved file transfer path. Document the
exact restore command and backup timestamp before replacing production data.

## Troubleshooting

App is not responding:

```bash
fly status --app finmat
fly logs --app finmat
fly machines list --app finmat
```

Daily digest did not run:

```bash
fly logs --app finmat
fly ssh console --app finmat --command "cd /app && python main.py --once"
```

Dashboard auth fails:

```bash
fly secrets list --app finmat
```

Database looks empty on a fresh day-0 install:

This is expected before the first trade is logged. Use the dashboard/API to log
initial trades, then let the scheduler run from SQLite.

Database unexpectedly lacks migrated legacy data:

```bash
fly ssh console --app finmat --command "sqlite3 /data/finmat.db '.tables'"
fly secrets set RUN_SQLITE_MIGRATION=1 --app finmat
fly machines restart --app finmat
```

Before running migration in production, confirm whether legacy source files are
present and current. The migration is idempotent, but stale legacy inputs can
still be misleading.

## Scaling Rule

Keep one machine:

```bash
fly scale count 1 --app finmat
```

Multiple machines can run duplicate schedulers and send duplicate alerts.
