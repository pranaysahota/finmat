"""
Tests for modules/news_sentiment.py — news fetching and sentiment scoring.
All network and API calls are mocked; no real requests are made.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from modules.news_sentiment import fetch_news, get_all_sentiment, score_sentiment


# ── fetch_news ────────────────────────────────────────────────


class TestFetchNews:
    """fetch_news parses feedparser entries and returns title strings."""

    def _make_feed(self, titles: list[str]) -> MagicMock:
        """Build a fake feedparser result with the given entry titles."""
        feed = MagicMock()
        feed.entries = [MagicMock(title=t) for t in titles]
        return feed

    def test_returns_list_of_title_strings(self):
        titles = ["MSFT up 3%", "Microsoft beats earnings", "Azure growth accelerates"]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news("MSFT stock news")
        assert result == titles

    def test_respects_max_items(self):
        titles = [f"Headline {i}" for i in range(10)]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news("MSFT stock news", max_items=3)
        assert len(result) == 3
        assert result == titles[:3]

    def test_returns_empty_list_on_feedparser_exception(self):
        with patch("modules.news_sentiment.feedparser.parse", side_effect=Exception("network error")):
            result = fetch_news("MSFT stock news")
        assert result == []

    def test_returns_empty_list_when_no_entries(self):
        feed = MagicMock()
        feed.entries = []
        with patch("modules.news_sentiment.feedparser.parse", return_value=feed):
            result = fetch_news("MSFT stock news")
        assert result == []

    def test_query_included_in_url(self):
        feed = MagicMock()
        feed.entries = []
        with patch("modules.news_sentiment.feedparser.parse", return_value=feed) as mock_parse:
            fetch_news("NVDA earnings")
        called_url = mock_parse.call_args.args[0]
        assert "NVDA" in called_url

    def test_default_max_items_is_five(self):
        titles = [f"H{i}" for i in range(10)]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news("MSFT stock news")
        assert len(result) == 5

    def test_returns_fewer_than_max_when_feed_has_fewer(self):
        titles = ["Only one headline"]
        with patch("modules.news_sentiment.feedparser.parse", return_value=self._make_feed(titles)):
            result = fetch_news("MSFT stock news", max_items=5)
        assert result == ["Only one headline"]


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
    """get_all_sentiment returns a dict keyed by every ticker passed in."""

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

    def test_fetch_news_called_once_per_ticker(self):
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

    def test_stock_query_contains_stock_news(self):
        with patch("modules.news_sentiment.fetch_news", return_value=[]) as mock_fetch:
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                get_all_sentiment(["MSFT"])
        query = mock_fetch.call_args.args[0]
        assert "stock news" in query

    def test_crypto_query_contains_cryptocurrency_news(self):
        with patch("modules.news_sentiment.fetch_news", return_value=[]) as mock_fetch:
            with patch("modules.news_sentiment.score_sentiment", return_value=self.MOCK_SENTIMENT):
                get_all_sentiment(["bitcoin"])
        query = mock_fetch.call_args.args[0]
        assert "cryptocurrency news" in query

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
