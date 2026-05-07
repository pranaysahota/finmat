"""
Tests for main.py — pipeline orchestration logic.
All downstream modules are mocked; no real prices, API, or Telegram calls are made.
"""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import main  # noqa: E402


# ── Shared mock data ──────────────────────────────────────────

MOCK_PRICES = {
    "MSFT": 430.0, "AAPL": 232.0, "NVDA": 140.0,
    "bitcoin": 96000.0, "ethereum": 2750.0,
}

MOCK_STATE = {
    "total_value":    8200.0,
    "total_cost":     8000.0,
    "total_pnl_usd":  200.0,
    "total_pnl_pct":  2.5,
    "crypto_weight":  14.8,
    "bucket_values":  {"Diversified": 4980.0, "Growth": 2010.0, "Crypto": 1210.0},
    "bucket_weights": {"Diversified": 60.7, "Growth": 24.5, "Crypto": 14.8},
    "holdings": {
        "MSFT": {"current_price": 430.0, "current_value": 1290.0,
                 "cost_basis": 1200.0, "pnl_pct": 7.5, "pnl_usd": 90.0, "bucket": "Diversified"},
    },
}

MOCK_CRITICAL_RULES = [
    {"level": "CRITICAL", "ticker": "NVDA", "rule": "stop_loss",
     "message": "🔴 NVDA down 25%"},
]

MOCK_HIGH_RULES = [
    {"level": "HIGH", "ticker": "MSFT", "rule": "take_profit",
     "message": "🟢 MSFT up 40%"},
]

MOCK_PERFORMANCE = {
    "since_inception_pct": 2.5,
    "since_inception_usd": 200.0,
    "last_7_days_pct":     1.2,
    "best_performer":      {"ticker": "MSFT", "pnl_pct": 7.5},
    "worst_performer":     {"ticker": "NVDA", "pnl_pct": 3.7},
    "total_snapshots":     8,
    "first_date":          "2026-02-17",
    "latest_date":         "2026-02-24",
}

MOCK_SENTIMENT = {
    "MSFT": {"score": 0.6, "label": "BULLISH", "summary": "Strong AI growth."},
}

# ── Patch helpers ─────────────────────────────────────────────

def _patch_pipeline(**overrides):
    """Return a dict of attribute-name → mock for use with patch.multiple('main', ...)."""
    defaults = {
        "is_market_open":                  MagicMock(return_value=True),
        "get_all_prices":                  MagicMock(return_value=MOCK_PRICES),
        "calculate_portfolio":             MagicMock(return_value=MOCK_STATE),
        "check_rules":                     MagicMock(return_value=[]),
        "check_bucket_drift":              MagicMock(return_value=[]),
        "get_performance_summary":         MagicMock(return_value=MOCK_PERFORMANCE),
        "get_all_sentiment":               MagicMock(return_value=MOCK_SENTIMENT),
        "get_macro_sentiment":             MagicMock(return_value={}),
        "get_weekly_analysis":             MagicMock(return_value="Gemini analysis text."),
        "get_weekly_sell_recommendations": MagicMock(return_value="MSFT — HOLD"),
        "send_critical_alert":             MagicMock(),
        "send_weekly_email":               MagicMock(),
        "load_history":                    MagicMock(return_value=[]),
    }
    # Accept "main.foo" keys for convenience and strip the prefix
    stripped = {k.removeprefix("main."): v for k, v in overrides.items()}
    defaults.update(stripped)
    return defaults


# ── run_price_check ───────────────────────────────────────────


class TestRunPriceCheck:
    """run_price_check runs the fast pipeline and fires critical alerts."""

    def test_calls_get_all_prices(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["get_all_prices"].assert_called_once()

    def test_calls_calculate_portfolio(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["calculate_portfolio"].assert_called_once_with(MOCK_PRICES)

    def test_calls_check_rules(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["check_rules"].assert_called_once_with(MOCK_STATE)

    def test_calls_check_bucket_drift(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["check_bucket_drift"].assert_called_once_with(MOCK_STATE)

    def test_sends_critical_alert_for_critical_rule(self):
        mocks = _patch_pipeline(**{
            "main.check_rules": MagicMock(return_value=MOCK_CRITICAL_RULES),
        })
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["send_critical_alert"].assert_called_once_with(
            "NVDA", "🔴 NVDA down 25%"
        )

    def test_does_not_send_alert_for_non_critical_rule(self):
        mocks = _patch_pipeline(**{
            "main.check_rules": MagicMock(return_value=MOCK_HIGH_RULES),
        })
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["send_critical_alert"].assert_not_called()

    def test_does_not_call_sentiment(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["get_all_sentiment"].assert_not_called()

    def test_does_not_raise_on_price_fetch_failure(self):
        mocks = _patch_pipeline(**{
            "main.get_all_prices": MagicMock(side_effect=Exception("network error")),
        })
        with patch.multiple("main", **mocks):
            main.run_price_check()  # must not raise

    def test_multiple_critical_alerts_each_sent(self):
        two_criticals = [
            {"level": "CRITICAL", "ticker": "NVDA", "rule": "stop_loss", "message": "NVDA down"},
            {"level": "CRITICAL", "ticker": "AAPL", "rule": "stop_loss", "message": "AAPL down"},
        ]
        mocks = _patch_pipeline(**{
            "main.check_rules": MagicMock(return_value=two_criticals),
        })
        with patch.multiple("main", **mocks):
            main.run_price_check()
        assert mocks["send_critical_alert"].call_count == 2


# ── run_daily_digest ──────────────────────────────────────────


class TestRunDailyDigest:
    """run_daily_digest sends digest when enough history exists."""

    def test_calls_send_weekly_email_when_performance_available(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_digest()
        mocks["send_weekly_email"].assert_called_once()

    def test_calls_get_all_prices_for_current_value(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_digest()
        mocks["get_all_prices"].assert_called_once()

    def test_does_not_raise_on_failure(self):
        mocks = _patch_pipeline(**{
            "main.get_all_prices": MagicMock(side_effect=Exception("network")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_digest()  # must not raise


# ── is_market_open ────────────────────────────────────────────


class TestIsMarketOpen:
    """is_market_open() gates on America/New_York weekday 09:30–16:00."""

    def _et(self, weekday: int, hour: int, minute: int) -> datetime:
        """Return a timezone-aware ET datetime. weekday: 0=Mon … 6=Sun.
        Anchored to 2026-02-23 (a confirmed Monday).
        """
        from datetime import timedelta
        base = datetime(2026, 2, 23, tzinfo=ZoneInfo("America/New_York"))
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=weekday)

    def test_true_during_market_hours_monday(self):
        with patch("main._current_et_time", return_value=self._et(0, 10, 0)):
            assert main.is_market_open() is True

    def test_true_at_open_boundary(self):
        """09:30 ET is exactly at open — should return True."""
        with patch("main._current_et_time", return_value=self._et(0, 9, 30)):
            assert main.is_market_open() is True

    def test_false_one_minute_before_open(self):
        with patch("main._current_et_time", return_value=self._et(0, 9, 29)):
            assert main.is_market_open() is False

    def test_false_at_close_boundary(self):
        """16:00 ET is exactly at close — should return False."""
        with patch("main._current_et_time", return_value=self._et(0, 16, 0)):
            assert main.is_market_open() is False

    def test_false_after_close(self):
        with patch("main._current_et_time", return_value=self._et(0, 16, 1)):
            assert main.is_market_open() is False

    def test_true_on_friday_during_hours(self):
        with patch("main._current_et_time", return_value=self._et(4, 14, 0)):
            assert main.is_market_open() is True

    def test_false_on_saturday(self):
        with patch("main._current_et_time", return_value=self._et(5, 12, 0)):
            assert main.is_market_open() is False

    def test_false_on_sunday(self):
        with patch("main._current_et_time", return_value=self._et(6, 12, 0)):
            assert main.is_market_open() is False

    def test_run_price_check_skips_pipeline_when_market_closed(self):
        mocks = _patch_pipeline(**{"is_market_open": MagicMock(return_value=False)})
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["get_all_prices"].assert_not_called()
        mocks["calculate_portfolio"].assert_not_called()

    def test_run_price_check_prints_market_closed_message(self, capsys):
        fake_et = self._et(5, 14, 0)  # Saturday 14:00 ET
        with patch("main._current_et_time", return_value=fake_et):
            with patch("main.is_market_open", return_value=False):
                main.run_price_check()
        assert "Market closed" in capsys.readouterr().out
