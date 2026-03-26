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

from modules.alerts import send_critical_alert, send_daily_briefing, send_message, send_weekly_digest


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

PERFORMANCE = {
    "since_inception_pct": 2.5,
    "since_inception_usd": 200.0,
    "last_7_days_pct":     1.2,
    "best_performer":      {"ticker": "MSFT", "pnl_pct": 7.5},
    "worst_performer":     {"ticker": "NVDA", "pnl_pct": 3.7},
    "total_snapshots":     8,
    "first_date":          "2026-02-17",
    "latest_date":         "2026-02-24",
}

TRIGGERED_RULES = [
    {"level": "CRITICAL", "ticker": "NVDA", "rule": "stop_loss",
     "message": "🔴 NVDA is down 25.0% — stop-loss threshold breached (-20%)"},
]

BUCKET_DRIFT = [
    {"level": "MEDIUM", "ticker": "Growth", "rule": "bucket_drift",
     "message": "📐 Growth bucket is underweight: 24.5% actual vs 25% target"},
]

DECISION_TEXT = (
    "MARKET MOOD: Cautiously bullish.\n\n"
    "PORTFOLIO STATUS: Portfolio performing well.\n\n"
    "ACTIONS REQUIRED:\n- No action needed\n\n"
    "WATCH LIST:\n- Monitor NVDA"
)


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


# ── send_daily_briefing ───────────────────────────────────────


class TestSendDailyBriefing:
    """send_daily_briefing formats a message and delegates to send_message."""

    def _captured_text(self, **kwargs) -> str:
        """Run send_daily_briefing and return the text passed to send_message."""
        captured = {}

        def fake_send(text: str) -> bool:
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_daily_briefing(**kwargs)

        return captured.get("text", "")

    def test_send_message_called_once(self):
        with patch("modules.alerts.send_message", return_value=True) as mock_send:
            send_daily_briefing(PORTFOLIO_STATE, DECISION_TEXT, [], [], {})
        assert mock_send.call_count == 1

    def test_header_is_briefing_without_alerts(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "📊" in text
        assert "Finance Agent — Daily Briefing" in text

    def test_header_has_alert_icon_when_rules_triggered(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=TRIGGERED_RULES, bucket_drift=[], performance={},
        )
        assert "🚨" in text

    def test_portfolio_value_in_message(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "8,200.00" in text

    def test_total_pnl_in_message(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "+200.00" in text

    def test_eur_usd_note_present(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "EUR" in text or "exchange rate" in text

    def test_decision_text_included(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "MARKET MOOD" in text

    def test_triggered_rules_section_present_when_alerts_exist(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=TRIGGERED_RULES, bucket_drift=[], performance={},
        )
        assert "Rules Triggered" in text
        assert "NVDA" in text

    def test_no_rules_section_when_no_alerts(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "Rules Triggered" not in text

    def test_bucket_drift_section_present_when_drift(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=BUCKET_DRIFT, performance={},
        )
        assert "Bucket Drift" in text

    def test_performance_footer_present_when_data(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance=PERFORMANCE,
        )
        assert "Since inception" in text
        assert "+2.50%" in text

    def test_no_performance_footer_when_empty(self):
        text = self._captured_text(
            portfolio_state=PORTFOLIO_STATE, decision=DECISION_TEXT,
            triggered_rules=[], bucket_drift=[], performance={},
        )
        assert "Since inception" not in text


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


# ── send_weekly_digest ────────────────────────────────────────


class TestSendWeeklyDigest:
    """send_weekly_digest formats and sends the weekly summary."""

    def _captured_text(self, performance: dict, portfolio_state: dict) -> str:
        captured = {}

        def fake_send(text: str) -> bool:
            captured["text"] = text
            return True

        with patch("modules.alerts.send_message", side_effect=fake_send):
            send_weekly_digest(performance, portfolio_state)

        return captured.get("text", "")

    def test_send_message_called(self):
        with patch("modules.alerts.send_message", return_value=True) as mock_send:
            send_weekly_digest(PERFORMANCE, PORTFOLIO_STATE)
        assert mock_send.call_count == 1

    def test_weekly_digest_header_present(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "Weekly Digest" in text

    def test_portfolio_value_in_digest(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "8,200.00" in text

    def test_best_performer_in_digest(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "MSFT" in text

    def test_worst_performer_in_digest(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "NVDA" in text

    def test_inception_return_in_digest(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "inception" in text.lower()
        assert "+2.50%" in text

    def test_irish_cgt_footer_present(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "CGT" in text
        assert "1,270" in text or "€1,270" in text

    def test_7_day_return_shown_when_available(self):
        text = self._captured_text(PERFORMANCE, PORTFOLIO_STATE)
        assert "+1.20%" in text

    def test_empty_performance_still_sends(self):
        with patch("modules.alerts.send_message", return_value=True) as mock_send:
            send_weekly_digest({}, PORTFOLIO_STATE)
        assert mock_send.call_count == 1
