#!/usr/bin/env bash
# read_logs.sh — read briefing logs from the live fly.io deployment.
#
# Usage:
#   ./scripts/read_logs.sh                  # today's runs (default)
#   ./scripts/read_logs.sh --last 7         # last 7 days
#   ./scripts/read_logs.sh --date 2026-03-24
#   ./scripts/read_logs.sh --flips-only

set -euo pipefail

APP="finmat"
ARGS="${*:---last 1}"

if ! command -v fly &>/dev/null; then
  echo "Error: fly CLI not found. Install from https://fly.io/docs/hands-on/install-flyctl/"
  exit 1
fi

echo "Fetching logs from ${APP}..."
fly ssh console -a "$APP" -C "cd /app && python scripts/review_logs.py ${ARGS}"
