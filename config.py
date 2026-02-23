"""App-level settings, file paths, risk rules, and scheduling config. Safe to commit."""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys (loaded from .env) ──────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── File Paths ───────────────────────────────────────────────
DATA_DIR              = os.path.join(os.path.dirname(__file__), "data")
HISTORY_FILE          = os.path.join(DATA_DIR, "portfolio_history.json")

# ── Risk Rules ───────────────────────────────────────────────
# Thresholds that trigger alerts when breached
RULES = {
    "stop_loss_pct":     -20,    # alert if any position is down 20% or more
    "take_profit_pct":    40,    # alert if any position is up 40% or more
    "crypto_max_weight":  20,    # alert if crypto exceeds 20% of total portfolio value
    "benchmark":         "VOO",  # compare overall performance against VOO
}

# ── Bucket Targets ───────────────────────────────────────────
# Target allocation (%) per bucket
BUCKET_TARGETS = {
    "ETFs":   60,
    "Stocks": 25,
    "Crypto": 15,
}

# ── Scheduling ───────────────────────────────────────────────
DAILY_BRIEFING_TIME   = "08:00"   # time to run full daily briefing
PRICE_CHECK_INTERVAL  = 1         # price check frequency in hours
