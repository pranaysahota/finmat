import os
from dotenv import load_dotenv

load_dotenv()

# API Keys
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "mock_alphavantage_key")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "mock_anthropic_key")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "mock_telegram_bot_token")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "mock_telegram_chat_id")

# Portfolio settings
PORTFOLIO = {
    "AAPL": 10,
    "TSLA": 5,
    "MSFT": 8,
}

# Alert thresholds
PRICE_DROP_THRESHOLD = 0.05   # 5% drop triggers alert
PRICE_RISE_THRESHOLD = 0.05   # 5% rise triggers alert
SENTIMENT_NEGATIVE_THRESHOLD = -0.3

# Scheduling
POLL_INTERVAL_SECONDS = 300   # Run every 5 minutes
