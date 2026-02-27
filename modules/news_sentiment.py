"""Fetches financial news headlines via Google News RSS and scores sentiment using Claude."""

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

import feedparser

# Allow direct invocation (python modules/news_sentiment.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ANTHROPIC_API_KEY

import anthropic

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

_NEUTRAL = {"score": 0.0, "label": "NEUTRAL", "summary": "No news found."}


def fetch_news(query: str, max_items: int = 5) -> list[str]:
    """Fetch recent headline titles from Google News RSS for a given query.

    Uses feedparser to parse the Google News RSS feed — no API key required.
    Returns only the plain title strings so that score_sentiment has clean input.

    Args:
        query:     Search query string e.g. "MSFT stock news".
        max_items: Maximum number of headlines to return (default 5).

    Returns:
        List of headline title strings, up to max_items.
        Empty list on any network or parse error.
    """
    try:
        url  = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
        feed = feedparser.parse(url)
        return [entry.title for entry in feed.entries[:max_items]]
    except Exception:
        # Any error (network, parse, attribute) → return empty list silently
        return []


def score_sentiment(label_for: str, headlines: list[str]) -> dict:
    """Score the sentiment of a set of headlines for a given label using Claude Haiku.

    Sends the headlines to Claude Haiku with a structured prompt and parses the
    JSON response. Strips markdown code fences before parsing so the model's
    output format doesn't cause failures.

    Args:
        label_for: Ticker symbol or theme label used in the prompt (e.g. "NVDA",
                   "AI_TECH_THEME"). Determines what the analysis is attributed to.
        headlines: List of headline strings to analyse. If empty, returns NEUTRAL.

    Returns:
        Dict with keys:
            score   (float)  — –1.0 (very bearish) to +1.0 (very bullish)
            label   (str)    — BEARISH | SLIGHTLY_BEARISH | NEUTRAL |
                               SLIGHTLY_BULLISH | BULLISH
            summary (str)    — one-sentence human-readable summary
        Returns NEUTRAL dict on any API or parse error.
    """
    if not headlines:
        return dict(_NEUTRAL)

    prompt = (
        f"Analyse these recent news headlines for {label_for} and return ONLY valid JSON "
        f"with exactly these keys: score (float from -1.0 to 1.0), "
        f"label (one of: BEARISH, SLIGHTLY_BEARISH, NEUTRAL, SLIGHTLY_BULLISH, BULLISH), "
        f"summary (one sentence).\n\n"
        f"Headlines:\n" + "\n".join(f"- {h}" for h in headlines)
    )

    try:
        client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 150,
            system     = "You are a financial sentiment analyser. Return only valid JSON.",
            messages   = [{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # Strip optional markdown code fences: ```json ... ``` or ``` ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        data = json.loads(raw)

        # Validate expected keys exist; fall back to NEUTRAL if malformed
        if not {"score", "label", "summary"}.issubset(data.keys()):
            return dict(_NEUTRAL)

        return {
            "score":   float(data["score"]),
            "label":   str(data["label"]),
            "summary": str(data["summary"]),
        }

    except Exception:
        return dict(_NEUTRAL)


def get_all_sentiment(tickers: list[str]) -> dict:
    """Fetch headlines and score sentiment for a list of stock tickers.

    Crypto tickers are identified by known coin IDs (lowercase). Stocks use
    "{ticker} stock news" as the query; crypto uses "{ticker} cryptocurrency news".

    Sentiment is only called during the daily briefing — not the hourly price check.
    Per CLAUDE.md: do NOT run sentiment on crypto tickers.

    Args:
        tickers: List of ticker symbols or coin ids to analyse.
                 Only stock tickers should be passed (crypto excluded per design).

    Returns:
        Dict of {ticker: sentiment_dict} for every ticker in the list.
        Each sentiment_dict has keys: score, label, summary.
    """
    results: dict = {}

    _CRYPTO_IDS = {"bitcoin", "ethereum", "btc", "eth"}

    for ticker in tickers:
        is_crypto = ticker.lower() in _CRYPTO_IDS
        query     = f"{ticker} cryptocurrency news" if is_crypto else f"{ticker} stock news"

        print(f"  📰 {ticker:<12} fetching headlines…")
        headlines = fetch_news(query)
        sentiment = score_sentiment(ticker, headlines)
        results[ticker] = sentiment
        print(f"  📰 {ticker:<12} {sentiment['label']} ({sentiment['score']:+.2f})")

    return results


def get_macro_sentiment(portfolio_state: dict) -> dict:
    """Fetch and score sentiment for cross-position macro themes based on portfolio composition.

    Runs 4 fixed queries covering the thematic overlaps across all three buckets:
    AI/Tech, Semiconductor, Defensive/Value, and Crypto. Each result includes
    the sentiment scores plus the list of portfolio tickers affected by that theme.

    Runs only during the daily briefing — not the hourly price check.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio(). Used to signal
                         which portfolio is being analysed (reserved for future
                         dynamic theme generation).

    Returns:
        Dict keyed by theme label, each value containing score, label, summary,
        and affected_tickers. Example:
            {
                "AI_TECH_THEME": {
                    "score": 0.4, "label": "SLIGHTLY_BULLISH",
                    "summary": "...", "affected_tickers": ["MSFT", "AAPL", ...]
                },
                ...
            }
        Returns empty dict on any error — never crashes the pipeline.
    """
    _THEMES = [
        {
            "query":             "AI technology stocks market outlook",
            "label_for":         "AI_TECH_THEME",
            "affected_tickers":  ["MSFT", "AAPL", "GOOG", "NVDA", "ASML"],
        },
        {
            "query":             "semiconductor chip industry news",
            "label_for":         "SEMICONDUCTOR_THEME",
            "affected_tickers":  ["NVDA", "ASML"],
        },
        {
            "query":             "financials energy healthcare stocks outlook",
            "label_for":         "DEFENSIVE_THEME",
            "affected_tickers":  ["JPM", "JNJ", "XOM", "BRK.B"],
        },
        {
            "query":             "bitcoin ethereum crypto market sentiment",
            "label_for":         "CRYPTO_THEME",
            "affected_tickers":  ["bitcoin", "ethereum"],
        },
    ]

    results: dict = {}
    try:
        for theme in _THEMES:
            print(f"  🌐 {theme['label_for']:<25} fetching headlines…")
            headlines = fetch_news(theme["query"])
            sentiment = score_sentiment(theme["label_for"], headlines)
            results[theme["label_for"]] = {
                **sentiment,
                "affected_tickers": theme["affected_tickers"],
            }
            print(
                f"  🌐 {theme['label_for']:<25} "
                f"{sentiment['label']} ({sentiment['score']:+.2f})"
            )
    except Exception:
        return {}

    return results


# ── Manual test ────────────────────────────────────────────────
if __name__ == "__main__":
    test_tickers = ["MSFT", "NVDA", "AAPL"]
    print("\n── Sentiment Analysis ──\n")
    sentiment = get_all_sentiment(test_tickers)
    print("\n── Results ──\n")
    for ticker, data in sentiment.items():
        print(f"  {ticker:<10} [{data['label']:<18}] {data['score']:+.2f}  {data['summary']}")
