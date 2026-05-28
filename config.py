"""App-level configuration — safe to commit.
Contains strategy context, risk rules, bucket targets, and file paths.
Current portfolio holdings are loaded from SQLite via modules/database.py.
portfolio/local.py is a legacy migration/fallback file only.
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STRATEGY CONTEXT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Total capital:   $8,000
# Horizon:         6–12 months
# Risk profile:    Moderate (balanced, Ireland CGT-optimised)
# Start date:      February 2026
# Bucket split:    60% Diversified / 25% Growth / 15% Crypto
# Tax note:        ETFs excluded — Irish exit tax (38%) + 8-year deemed disposal
#                  makes them unfavourable vs. individual stocks at CGT 33%.
#                  All positions subject to Irish CGT at 33% on actual disposal only.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys (loaded from .env) ──────────────────────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")   # Claude API key for sentiment + decisions
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # Telegram bot token for sending alerts
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")    # Telegram chat ID to deliver messages to

# ── Bucket Targets ───────────────────────────────────────────
# Target allocation as % of total portfolio per bucket
BUCKET_TARGETS = {
    "Diversified": 60,   # 60% — multi-sector stocks replacing ETFs (CGT 33% vs exit tax 38%)
    "Growth":      25,   # 25% — higher-risk AI and tech plays
    "Crypto":      15,   # 15% — BTC + ETH
}

# ── Crypto Activation ────────────────────────────────────────
# Set to True when the first crypto purchase is made via trade.py.
# When False, the Crypto bucket is excluded from all calculations and
# price fetches — drift targets are recalculated across Diversified + Growth only.
CRYPTO_ACTIVE = False

# ── Risk Rules ───────────────────────────────────────────────
# Thresholds that trigger alerts when breached
RULES = {
    "stop_loss_pct":     -20,     # alert when any position is down ≥ 20%
    "take_profit_pct":    40,     # alert when any position is up ≥ 40%
    "crypto_max_weight":  20,     # alert when crypto exceeds 20% of total portfolio value
    "bucket_drift_pct":    5,     # alert when any bucket drifts > 5pp from its target weight
    "benchmark":         "MSFT",  # largest position — use as internal performance anchor
}

# ── News Sources ─────────────────────────────────────────────
# URL registries used by modules/news_sentiment.py.
# {ticker} is interpolated at call time for ticker_specific templates.
NEWS_SOURCES = {
    # Used by get_all_sentiment() — one feed per ticker, interpolate {ticker}
    "ticker_specific": [
        "https://finance.yahoo.com/rss/headline?s={ticker}",
        "https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en",
    ],

    # Used by get_macro_sentiment() — general market and macro themes
    "market_general": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    ],

    # Used by get_macro_sentiment() — European and sector coverage (ASML, XOM)
    "european_and_sector": [
        "https://feeds.marketwatch.com/marketwatch/marketpulse/",
        "https://news.google.com/rss/search?q=european+stocks+semiconductor&hl=en-US&gl=US&ceid=US:en",
    ],

    # Used by get_macro_sentiment() — only when CRYPTO_ACTIVE is True
    "crypto": [
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "https://news.google.com/rss/search?q=bitcoin+ethereum+crypto+market&hl=en-US&gl=US&ceid=US:en",
    ],
}

# ── File Paths (pathlib — not raw strings) ───────────────────
# On Fly.io the persistent volume is mounted at /data; locally use data/
DATA_DIR = Path("/data") if os.path.exists("/data") else Path("data/")
DB_PATH  = DATA_DIR / "finmat.db"

PATHS = {
    "DATA_DIR": DATA_DIR,
}

# ── Load Private Portfolio ───────────────────────────────────
# Holdings are stored in SQLite (data/finmat.db).
# portfolio/local.py is kept as a legacy fallback for initial migration.

from modules.database import get_all_holdings, init_db

init_db()  # ensure tables exist on import


def load_portfolio() -> dict:
    """Load PORTFOLIO fresh from SQLite on every call.

    Use this at the start of each pipeline run to pick up trades logged
    via trade.py or the UI without requiring a process restart.
    """
    return get_all_holdings()


PORTFOLIO = load_portfolio()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# USAGE — what each module imports from this file
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# modules/price_fetcher.py    → PORTFOLIO
# modules/portfolio.py        → PORTFOLIO, RULES, BUCKET_TARGETS, CRYPTO_ACTIVE
# modules/news_sentiment.py   → ANTHROPIC_API_KEY, CRYPTO_ACTIVE, NEWS_SOURCES
# modules/decision_engine.py  → ANTHROPIC_API_KEY, RULES
# modules/alerts.py           → TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# modules/history.py          → PATHS
# trade.py                    → PATHS
# modules/price_fetcher.py    → CRYPTO_ACTIVE
# main.py                     → PORTFOLIO, RULES, PATHS, load_portfolio, CRYPTO_ACTIVE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
