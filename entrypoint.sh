#!/bin/sh
# Startup entrypoint for Fly.io deployment.
# Starts the SQLite-backed UI + scheduler. Legacy file-to-SQLite migration is
# opt-in via RUN_SQLITE_MIGRATION=1 for old deployments only.
set -e

if [ "${RUN_SQLITE_MIGRATION:-0}" = "1" ]; then
    if [ -n "$PORTFOLIO_LOCAL_PY" ]; then
        echo "$PORTFOLIO_LOCAL_PY" | base64 -d > /app/portfolio/local.py
        echo "✓ portfolio/local.py reconstructed from secret"
    fi

    # Copy legacy trades file to persistent volume if not already there
    if [ -f /app/data/trades.json ] && [ ! -f /data/trades.json ]; then
        cp /app/data/trades.json /data/trades.json
        echo "✓ Copied trades.json to /data/"
    fi

    # Run migration from legacy files into SQLite.
    python scripts/migrate_to_sqlite.py
else
    echo "✓ Skipping legacy SQLite migration (set RUN_SQLITE_MIGRATION=1 to enable)"
    python -c "from modules.database import init_db; init_db()"
    echo "✓ SQLite database ready"
fi

# Start the UI server in the background
python -m flask --app ui.app run --host 0.0.0.0 --port 5001 &
echo "✓ UI server started on port 5001"

exec python main.py
