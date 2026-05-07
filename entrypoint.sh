#!/bin/sh
# Startup entrypoint for Fly.io deployment.
# Reconstructs portfolio/local.py from secret (needed for initial migration),
# copies legacy data files to persistent volume, runs pending migrations,
# then starts the agent + UI.
set -e

if [ -n "$PORTFOLIO_LOCAL_PY" ]; then
    echo "$PORTFOLIO_LOCAL_PY" | base64 -d > /app/portfolio/local.py
    echo "✓ portfolio/local.py reconstructed from secret"
fi

# Copy legacy trades file to persistent volume if not already there
if [ -f /app/data/trades.json ] && [ ! -f /data/trades.json ]; then
    cp /app/data/trades.json /data/trades.json
    echo "✓ Copied trades.json to /data/"
fi

# Run migrations (idempotent — skips if already applied)
python scripts/migrate_to_sqlite.py

# Start the UI server in the background
python -m flask --app ui.app run --host 0.0.0.0 --port 5001 &
echo "✓ UI server started on port 5001"

exec python main.py
