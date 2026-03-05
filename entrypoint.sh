#!/bin/sh
# Startup entrypoint for Fly.io deployment.
# Reconstructs portfolio/local.py from the PORTFOLIO_LOCAL_PY secret (base64-encoded),
# then starts the agent. This keeps real holdings out of the Git repo entirely.
set -e

if [ -n "$PORTFOLIO_LOCAL_PY" ]; then
    echo "$PORTFOLIO_LOCAL_PY" | base64 -d > /app/portfolio/local.py
    echo "✓ portfolio/local.py reconstructed from secret"
else
    echo "⚠️  PORTFOLIO_LOCAL_PY not set — using existing portfolio/local.py"
fi

exec python main.py
