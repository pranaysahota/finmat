"""
Tests for modules/alerts.py — Telegram message formatting and sending.
All HTTP calls are mocked; no real Telegram requests are made.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from modules.alerts import send_critical_alert, send_message


# ── Shared test data ──────────────────────────────────────────

PORTFOLIO_STATE = {
    "total_value":    8200.00,
    "total_pnl_usd":  200.00,
    "total_pnl_pct":  2.50,
    "bucket_values":  {"Diversified": 4980.0, "Growth": 2010.0},
    "bucket_weights": {"Diversified": 71.2, "Growth": 28.8},
    "holdings": {
        "MSFT": {"current_price": 430.0, "current_value": 1290.0,
                 "pnl_pct": 7.5, "pnl_usd": 90.0, "bucket": "Diversified"},
    },
}


def _http_ok() -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    return mock


def _http_error() -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status.side_effect = Exception("HTTP 403")
    return mock


# ── send_message ──────────────────────────────────────────────


class TestSendMessage:
    """send_message POSTs to Telegram and returns True/False."""

    def test_returns_true_on_success(self):
        with patch("modules.alerts.requests.post", return_value=_http_ok()):
            result = send_message("Hello")
        assert result is True

    def test_returns_false_on_http_error(self):
        with patch("modules.alerts.requests.post", return_value=_http_error()):
            result = send_message("Hello")
        assert result is False

    def test_returns_false_on_connection_error(self):
        with patch("modules.alerts.requests.post", side_effect=Exception("timeout")):
            result = send_message("Hello")
        assert result is False

    def test_does_not_raise_on_error(self):
        with patch("modules.alerts.requests.post", side_effect=RuntimeError("fail")):
            result = send_message("Hello")
        assert result is False

    def test_parse_mode_is_html(self):
        with patch("modules.alerts.requests.post", return_value=_http_ok()) as mock_post:
            send_message("Hello")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["parse_mode"] == "HTML"

    def test_text_included_in_payload(self):
        with patch("modules.alerts.requests.post", return_value=_http_ok()) as mock_post:
            send_message("Test message")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["text"] == "Test message"

    def test_url_contains_token(self):
        with patch("modules.alerts.requests.post", return_value=_http_ok()) as mock_post:
            with patch("modules.alerts.TELEGRAM_BOT_TOKEN", "mytoken123"):
                send_message("hello")
        called_url = mock_post.call_args.args[0]
        assert "mytoken123" in called_url

    def test_long_message_split_into_multiple_posts(self):
        """A message exceeding 4096 chars is sent as multiple POST requests."""
        long_text = "\n".join([f"line {i}" for i in range(500)])  # well over 4096 chars
        with patch("modules.alerts.requests.post", return_value=_http_ok()) as mock_post:
            result = send_message(long_text)
        assert mock_post.call_count > 1
        assert result is True

    def test_each_chunk_within_limit(self):
        """Every chunk sent to Telegram must be ≤ 4096 characters."""
        long_text = "\n".join([f"line {i}: {'x' * 20}" for i in range(300)])
        sent_chunks: list[str] = []
        def fake_post(url, json, timeout):
            sent_chunks.append(json["text"])
            return _http_ok()
        with patch("modules.alerts.requests.post", side_effect=fake_post):
            send_message(long_text)
        for chunk in sent_chunks:
            assert len(chunk) <= 4096, f"Chunk too long: {len(chunk)}"

    def test_short_message_single_post(self):
        """A message under 4096 chars is sent in a single POST."""
        with patch("modules.alerts.requests.post", return_value=_http_ok()) as mock_post:
            send_message("short message")
        assert mock_post.call_count == 1

    def test_returns_false_if_any_chunk_fails(self):
        """Returns False if any chunk in a multi-part send fails."""
        long_text = "\n".join([f"line {i}" for i in range(500)])
        call_count = [0]
        def fail_second(url, json, timeout):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("network error")
            return _http_ok()
        with patch("modules.alerts.requests.post", side_effect=fail_second):
            result = send_message(long_text)
        assert result is False


# ── send_critical_alert ───────────────────────────────────────


class TestSendCriticalAlert:
    """send_critical_alert wraps a CRITICAL message and calls send_message."""

    def test_send_message_called(self):
        with patch("modules.alerts.send_message", return_value=True) as mock_send:
            send_critical_alert("NVDA", "NVDA is down 25%")
        assert mock_send.call_count == 1

    def test_message_contains_ticker(self):
        captured = {}

        def fake_send(text):
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_critical_alert("NVDA", "NVDA is down 25%")

        assert "NVDA" in captured["text"]

    def test_message_contains_critical_keyword(self):
        captured = {}

        def fake_send(text):
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_critical_alert("NVDA", "down 25%")

        assert "CRITICAL" in captured["text"]

    def test_red_emoji_in_message(self):
        captured = {}

        def fake_send(text):
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_critical_alert("MSFT", "stop loss hit")

        assert "🔴" in captured["text"]

    def test_alert_message_included(self):
        captured = {}

        def fake_send(text):
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_critical_alert("MSFT", "stop loss at -22%")

        assert "stop loss at -22%" in captured["text"]
