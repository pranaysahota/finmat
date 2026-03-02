"""
Tests for modules/news_sentiment.py — news fetching and sentiment scoring.
All network and API calls are mocked; no real requests are made.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.news_sentiment as ns_mod
from modules.news_sentiment import (
    fetch_news,
    get_all_sentiment,
    get_macro_sentiment,
    score_sentiment,
)


# ── fetch_news ────────────────────────────────────────────────


class TestFetchNews:
    """fetch_news aggregates headlines from a list of URLs and deduplicates."""

    URLS = ["https://example.com/feed1", "https://example.com/feed2"]

    def _make_feed(self, titles: list[str]) -> MagicMock:
        """Build a fake feedparser result with the given entry titles."""
        feed = MagicMock()
        feed.entries = [MagicMock(title=t) for t in titles]
        return feed

    def test_returns_list_of_title_strings(self):
        titles = ["MSFT up 3%", "Microsoft beats earnings", "Azure growth accelerates"]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news(["https://example.com/feed"])
        assert result == titles

    def test_respects_max_items(self):
        titles = [f"Headline {i}" for i in range(10)]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news(["https://example.com/feed"], max_items=3)
        assert len(result) == 3
        assert result == titles[:3]

    def test_returns_empty_list_on_feedparser_exception(self):
        with patch("modules.news_sentiment.feedparser.parse", side_effect=Exception("network error")):
            result = fetch_news(["https://example.com/feed"])
        assert result == []

    def test_returns_empty_list_when_no_entries(self):
        feed = MagicMock()
        feed.entries = []
        with patch("modules.news_sentiment.feedparser.parse", return_value=feed):
            result = fetch_news(["https://example.com/feed"])
        assert result == []

    def test_default_max_items_is_five(self):
        titles = [f"H{i}" for i in range(10)]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news(["https://example.com/feed"])
        assert len(result) == 5

    def test_returns_fewer_than_max_when_feed_has_fewer(self):
        titles = ["Only one headline"]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news(["https://example.com/feed"], max_items=5)
        assert result == ["Only one headline"]

    def test_empty_url_list_returns_empty_list(self):
        result = fetch_news([])
        assert result == []

    def test_deduplicates_headlines_across_urls(self):
        shared   = "Shared headline"
        unique_a = "Only in feed A"
        unique_b = "Only in feed B"
        feed_a = self._make_feed([shared, unique_a])
        feed_b = self._make_feed([shared, unique_b])
        with patch("modules.news_sentiment.feedparser.parse", side_effect=[feed_a, feed_b]):
            result = fetch_news(["https://a.com/rss", "https://b.com/rss"], max_items=10)
        assert result.count(shared) == 1
        assert unique_a in result
        assert unique_b in result

    def test_collects_from_multiple_urls(self):
        feed_a = self._make_feed(["A1", "A2"])
        feed_b = self._make_feed(["B1", "B2"])
        with patch("modules.news_sentiment.feedparser.parse", side_effect=[feed_a, feed_b]):
            result = fetch_news(["https://a.com/rss", "https://b.com/rss"], max_items=10)
        assert "A1" in result
        assert "B1" in result

    def test_skips_failed_url_silently_and_returns_from_working_url(self):
        good_feed = self._make_feed(["Good headline"])
        with patch(
            "modules.news_sentiment.feedparser.parse",
            side_effect=[Exception("timeout"), good_feed],
        ):
            result = fetch_news(["https://dead.com/rss", "https://live.com/rss"])
        assert result == ["Good headline"]

    def test_returns_empty_when_all_urls_fail(self):
        with patch(
            "modules.news_sentiment.feedparser.parse",
            side_effect=Exception("all down"),
        ):
            result = fetch_news(["https://a.com/rss", "https://b.com/rss"])
        assert result == []

    def test_total_capped_at_max_items_across_feeds(self):
        # Two feeds each with 5 unique headlines, max_items=5 → return only 5 total
        feed_a = self._make_feed([f"A{i}" for i in range(5)])
        feed_b = self._make_feed([f"B{i}" for i in range(5)])
        with patch("modules.news_sentiment.feedparser.parse", side_effect=[feed_a, feed_b]):
            result = fetch_news(["https://a.com/rss", "https://b.com/rss"], max_items=5)
        assert len(result) == 5


# ── score_sentiment ───────────────────────────────────────────


VALID_RESPONSE = json.dumps({
    "score":   0.7,
    "label":   "BULLISH",
    "summary": "Microsoft shows strong momentum on AI-driven revenue.",
})

NEUTRAL_RESPONSE = {"score": 0.0, "label": "NEUTRAL", "summary": "No news found."}


def _api_response(text: str) -> MagicMock:
    """Build a fake anthropic Messages response object."""
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


class TestScoreSentiment:
    """score_sentiment returns structured dict from Claude Haiku or neutral fallback."""

    def test_returns_neutral_when_headlines_empty(self):
        result = score_sentiment("MSFT", [])
        assert result == {"score": 0.0, "label": "NEUTRAL", "summary": "No news found."}

    def test_returns_score_label_summary_on_success(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(VALID_RESPONSE)
            result = score_sentiment("MSFT", ["Good headline"])
        assert result["score"] == 0.7
        assert result["label"] == "BULLISH"
        assert "Microsoft" in result["summary"]

    def test_score_is_float(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(VALID_RESPONSE)
            result = score_sentiment("MSFT", ["Some headline"])
        assert isinstance(result["score"], float)

    def test_strips_markdown_code_fence(self):
        fenced = "```json\n" + VALID_RESPONSE + "\n```"
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(fenced)
            result = score_sentiment("MSFT", ["Headline"])
        assert result["label"] == "BULLISH"

    def test_strips_plain_code_fence(self):
        fenced = "```\n" + VALID_RESPONSE + "\n```"
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(fenced)
            result = score_sentiment("MSFT", ["Headline"])
        assert result["label"] == "BULLISH"

    def test_returns_neutral_on_api_exception(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = Exception("API down")
            result = score_sentiment("MSFT", ["Headline"])
        assert result == NEUTRAL_RESPONSE

    def test_returns_neutral_on_malformed_json(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response("not json at all")
            result = score_sentiment("MSFT", ["Headline"])
        assert result == NEUTRAL_RESPONSE

    def test_returns_neutral_when_keys_missing_from_json(self):
        bad_json = json.dumps({"score": 0.5})   # label and summary missing
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(bad_json)
            result = score_sentiment("MSFT", ["Headline"])
        assert result == NEUTRAL_RESPONSE

    def test_correct_model_used(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(VALID_RESPONSE)
            score_sentiment("MSFT", ["Headline"])
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_ticker_appears_in_prompt(self):
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(VALID_RESPONSE)
            score_sentiment("NVDA", ["Headline"])
        call_kwargs = mock_create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "NVDA" in user_content

    def test_all_headlines_appear_in_prompt(self):
        headlines = ["Headline A", "Headline B"]
        with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(VALID_RESPONSE)
            score_sentiment("MSFT", headlines)
        user_content = mock_create.call_args.kwargs["messages"][0]["content"]
        for h in headlines:
            assert h in user_content

    def test_various_valid_labels_accepted(self):
        for label in ("BEARISH", "SLIGHTLY_BEARISH", "NEUTRAL", "SLIGHTLY_BULLISH", "BULLISH"):
            resp = json.dumps({"score": 0.0, "label": label, "summary": "ok"})
            with patch("modules.news_sentiment.anthropic.Anthropic") as MockClient:
                MockClient.return_value.messages.create.return_value = _api_response(resp)
                result = score_sentiment("MSFT", ["Headline"])
            assert result["label"] == label


# ── get_all_sentiment ─────────────────────────────────────────


class TestGetAllSentiment:
    """get_all_sentiment returns a dict keyed by every stock ticker passed in."""

    MOCK_SENTIMENT = {"score": 0.5, "label": "SLIGHTLY_BULLISH", "summary": "Positive."}

    def test_returns_dict_keyed_by_tickers(self):
        tickers = ["MSFT", "NVDA", "AAPL"]
        with patch("modules.news_sentiment.fetch_news",      return_value=["h1", "h2"]):
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                result = get_all_sentiment(tickers)
        assert set(result.keys()) == set(tickers)

    def test_each_ticker_sentiment_has_required_keys(self):
        with patch("modules.news_sentiment.fetch_news",      return_value=["h1"]):
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                result = get_all_sentiment(["MSFT"])
        assert {"score", "label", "summary"}.issubset(result["MSFT"].keys())

    def test_fetch_news_called_once_per_stock_ticker(self):
        tickers = ["MSFT", "NVDA"]
        with patch("modules.news_sentiment.fetch_news",      return_value=[]) as mock_fetch:
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                get_all_sentiment(tickers)
        assert mock_fetch.call_count == len(tickers)

    def test_score_sentiment_called_once_per_ticker(self):
        tickers = ["MSFT", "NVDA", "AAPL"]
        with patch("modules.news_sentiment.fetch_news",      return_value=[]):
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT) as mock_score:
                get_all_sentiment(tickers)
        assert mock_score.call_count == len(tickers)

    def test_fetch_news_called_with_url_list_containing_ticker(self):
        with patch("modules.news_sentiment.fetch_news", return_value=[]) as mock_fetch:
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                get_all_sentiment(["MSFT"])
        urls = mock_fetch.call_args.args[0]
        assert isinstance(urls, list)
        assert any("MSFT" in u for u in urls)

    def test_crypto_ticker_is_skipped(self):
        with patch("modules.news_sentiment.fetch_news", return_value=[]) as mock_fetch:
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                result = get_all_sentiment(["bitcoin"])
        assert mock_fetch.call_count == 0
        assert "bitcoin" not in result

    def test_mixed_list_skips_crypto_keeps_stocks(self):
        with patch("modules.news_sentiment.fetch_news",      return_value=[]):
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                result = get_all_sentiment(["MSFT", "bitcoin", "NVDA", "ethereum"])
        assert "MSFT" in result
        assert "NVDA" in result
        assert "bitcoin" not in result
        assert "ethereum" not in result

    def test_empty_ticker_list_returns_empty_dict(self):
        result = get_all_sentiment([])
        assert result == {}

    def test_headlines_passed_to_score_sentiment(self):
        mock_headlines = ["Big headline", "Another headline"]
        with patch("modules.news_sentiment.fetch_news",      return_value=mock_headlines):
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT) as mock_score:
                get_all_sentiment(["MSFT"])
        _, called_headlines = mock_score.call_args.args
        assert called_headlines == mock_headlines


# ── get_macro_sentiment ───────────────────────────────────────


class TestGetMacroSentiment:
    """get_macro_sentiment returns theme-level sentiment; CRYPTO_THEME gated by CRYPTO_ACTIVE."""

    MOCK_SENTIMENT = {"score": 0.2, "label": "SLIGHTLY_BULLISH", "summary": "Markets steady."}
    MOCK_STATE     = {}

    def test_returns_three_themes_when_crypto_inactive(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news",      return_value=["h1"]):
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    result = get_macro_sentiment(self.MOCK_STATE)
        assert set(result.keys()) == {"AI_TECH_THEME", "SEMICONDUCTOR_THEME", "DEFENSIVE_THEME"}

    def test_crypto_theme_absent_when_crypto_inactive(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news",      return_value=["h1"]):
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    result = get_macro_sentiment(self.MOCK_STATE)
        assert "CRYPTO_THEME" not in result

    def test_crypto_theme_present_when_crypto_active(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", True):
            with patch("modules.news_sentiment.fetch_news",      return_value=["h1"]):
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    result = get_macro_sentiment(self.MOCK_STATE)
        assert "CRYPTO_THEME" in result

    def test_each_theme_has_affected_tickers(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news",      return_value=["h1"]):
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    result = get_macro_sentiment(self.MOCK_STATE)
        for theme_data in result.values():
            assert "affected_tickers" in theme_data
            assert isinstance(theme_data["affected_tickers"], list)

    def test_fetch_news_called_with_max_items_8(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news", return_value=[]) as mock_fetch:
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    get_macro_sentiment(self.MOCK_STATE)
        for c in mock_fetch.call_args_list:
            assert c.kwargs.get("max_items", c.args[1] if len(c.args) > 1 else None) == 8

    def test_returns_empty_dict_on_exception(self):
        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news",      side_effect=Exception("crash")):
                result = get_macro_sentiment(self.MOCK_STATE)
        assert result == {}

    def test_ai_theme_urls_include_market_general_sources(self):
        """AI_TECH_THEME URL list should include both market_general feeds."""
        captured_urls: list[list[str]] = []

        def capture_fetch(urls, **kwargs):
            captured_urls.append(urls)
            return []

        with patch.object(ns_mod, "CRYPTO_ACTIVE", False):
            with patch("modules.news_sentiment.fetch_news", side_effect=capture_fetch):
                with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                    get_macro_sentiment(self.MOCK_STATE)

        from config import NEWS_SOURCES
        ai_urls = captured_urls[0]  # AI_TECH_THEME is first
        for src in NEWS_SOURCES["market_general"]:
            assert src in ai_urls
