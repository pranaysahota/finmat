"""App-level configuration — safe to commit.
Contains strategy context, risk rules, bucket targets, and file paths.
Portfolio holdings live in portfolio/local.py (gitignored).
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
PATHS = {
    "DATA_DIR":     Path("data/"),                         # directory for all runtime data files
    "HISTORY_FILE": Path("data/portfolio_history.json"),   # daily portfolio snapshot history
    "TRADES_FILE":  Path("data/trades.json"),              # permanent trade log (appended by trade.py)
}

# ── Scheduling ───────────────────────────────────────────────
DAILY_BRIEFING_TIME  = "08:00"  # time to run the full daily briefing (HH:MM)
PRICE_CHECK_INTERVAL = 1        # how often to check prices, in hours

# ── Load Private Portfolio ───────────────────────────────────
# portfolio/local.py is gitignored and holds your real holdings.
# It is never committed. See portfolio/local.example.py for the structure.
try:
    from portfolio.local import PORTFOLIO
except ModuleNotFoundError:
    raise SystemExit(
        "\n❌ portfolio/local.py not found.\n"
        "Copy portfolio/local.example.py → portfolio/local.py "
        "and fill in your real holdings.\n"
    )

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
# main.py                     → PORTFOLIO, RULES, PATHS, DAILY_BRIEFING_TIME, PRICE_CHECK_INTERVAL
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
