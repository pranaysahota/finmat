"""Fetches financial news headlines from multiple RSS sources and scores sentiment using Claude."""

import json
import sys
from pathlib import Path

import feedparser
import requests as _requests

# Allow direct invocation (python modules/news_sentiment.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import ANTHROPIC_API_KEY, CRYPTO_ACTIVE, NEWS_SOURCES

import anthropic

_NEUTRAL = {"score": 0.0, "label": "NEUTRAL", "summary": "No news found."}
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def fetch_news(urls: list[str], max_items: int = 5) -> list[str]:
    """Fetch and aggregate headlines from a list of RSS feed URLs.

    Pre-fetches each URL with requests (browser User-Agent) then passes the
    content to feedparser. Many financial RSS feeds block the default feedparser
    User-Agent, returning empty responses despite HTTP 200.

    Args:
        urls:      List of RSS feed URLs to fetch from.
        max_items: Maximum headlines to collect from each feed and to return
                   in total (default 5).

    Returns:
        Deduplicated list of headline title strings, up to max_items.
        Empty list if all feeds fail or return no items.
    """
    seen:      set[str]  = set()
    headlines: list[str] = []

    for url in urls:
        try:
            response = _requests.get(url, headers=_HEADERS, timeout=10)
            feed     = feedparser.parse(response.content)
            items    = [entry.title for entry in feed.entries[:max_items]]
        except Exception:
            continue  # dead feed — skip silently

        if not items:
            continue

        for title in items:
            if title not in seen:
                seen.add(title)
                headlines.append(title)

    return headlines[:max_items]


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

    Uses NEWS_SOURCES["ticker_specific"] URL templates, fetching from multiple
    sources per ticker and deduplicating headlines before scoring. Crypto
    tickers are skipped — per design, sentiment runs on stocks only.

    Args:
        tickers: List of ticker symbols to analyse. Crypto tickers are ignored.

    Returns:
        Dict of {ticker: sentiment_dict} for every stock ticker in the list.
        Each sentiment_dict has keys: score, label, summary.
    """
    results:   dict      = {}
    _CRYPTO_IDS          = {"bitcoin", "ethereum", "btc", "eth"}
    stock_tickers        = [t for t in tickers if t.lower() not in _CRYPTO_IDS]
    total                = len(stock_tickers)

    for n, ticker in enumerate(stock_tickers, 1):
        urls      = [tmpl.format(ticker=ticker) for tmpl in NEWS_SOURCES["ticker_specific"]]
        print(f"  📰 Fetching sentiment: {ticker} ({n} of {total})")
        headlines = fetch_news(urls, max_items=5)
        sentiment = score_sentiment(ticker, headlines)
        results[ticker] = sentiment
        print(f"  📰 {ticker:<12} {sentiment['label']} ({sentiment['score']:+.2f})")

    return results


def get_macro_sentiment(portfolio_state: dict) -> dict:
    """Fetch and score sentiment for cross-position macro themes.

    Builds URL lists from the NEWS_SOURCES registry for each theme.
    CRYPTO_THEME is only included when CRYPTO_ACTIVE is True.
    Each theme fetches max_items=8 headlines for broader reasoning coverage.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio(). Reserved for
                         future dynamic theme generation.

    Returns:
        Dict keyed by theme label, each value containing score, label, summary,
        and affected_tickers. Returns empty dict on any error.
    """
    _THEMES = [
        {
            "urls": NEWS_SOURCES["market_general"] + [
                "https://news.google.com/rss/search?q=AI+technology+stocks+outlook"
                "&hl=en-US&gl=US&ceid=US:en",
            ],
            "label_for":        "AI_TECH_THEME",
            "affected_tickers": ["MSFT", "AAPL", "GOOG", "NVDA", "ASML"],
        },
        {
            "urls": NEWS_SOURCES["european_and_sector"] + [
                "https://news.google.com/rss/search?q=semiconductor+chip+industry"
                "&hl=en-US&gl=US&ceid=US:en",
            ],
            "label_for":        "SEMICONDUCTOR_THEME",
            "affected_tickers": ["NVDA", "ASML"],
        },
        {
            "urls": NEWS_SOURCES["market_general"] + [
                "https://news.google.com/rss/search?q=financials+energy+healthcare+stocks"
                "&hl=en-US&gl=US&ceid=US:en",
            ],
            "label_for":        "DEFENSIVE_THEME",
            "affected_tickers": ["JPM", "JNJ", "XOM", "BRK.B"],
        },
    ]

    if CRYPTO_ACTIVE:
        _THEMES.append({
            "urls":             NEWS_SOURCES["crypto"],
            "label_for":        "CRYPTO_THEME",
            "affected_tickers": ["bitcoin", "ethereum"],
        })

    results: dict = {}
    try:
        for theme in _THEMES:
            print(f"  🌐 {theme['label_for']:<25} fetching headlines…")
            headlines = fetch_news(theme["urls"], max_items=8)
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
