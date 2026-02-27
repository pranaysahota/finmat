"""
Tests for main.py — pipeline orchestration logic.
All downstream modules are mocked; no real prices, API, or Telegram calls are made.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

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

MOCK_DECISION = "MARKET MOOD: Bullish.\n\nPORTFOLIO STATUS: All good."

# ── Patch helpers ─────────────────────────────────────────────

def _patch_pipeline(**overrides):
    """Return a dict of attribute-name → mock for use with patch.multiple('main', ...)."""
    defaults = {
        "get_all_prices":          MagicMock(return_value=MOCK_PRICES),
        "calculate_portfolio":     MagicMock(return_value=MOCK_STATE),
        "check_rules":             MagicMock(return_value=[]),
        "check_bucket_drift":      MagicMock(return_value=[]),
        "save_snapshot":           MagicMock(),
        "get_performance_summary": MagicMock(return_value=MOCK_PERFORMANCE),
        "get_all_sentiment":       MagicMock(return_value=MOCK_SENTIMENT),
        "get_macro_sentiment":     MagicMock(return_value={}),
        "get_decision":            MagicMock(return_value=MOCK_DECISION),
        "send_daily_briefing":     MagicMock(),
        "send_critical_alert":     MagicMock(),
        "send_weekly_digest":      MagicMock(),
        "load_history":            MagicMock(return_value=[]),
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

    def test_does_not_save_snapshot(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_price_check()
        mocks["save_snapshot"].assert_not_called()

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


# ── run_daily_briefing ────────────────────────────────────────


class TestRunDailyBriefing:
    """run_daily_briefing runs the full pipeline in order."""

    def test_calls_all_pipeline_steps(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        mocks["get_all_prices"].assert_called_once()
        mocks["calculate_portfolio"].assert_called_once()
        mocks["check_rules"].assert_called_once()
        mocks["check_bucket_drift"].assert_called_once()
        mocks["save_snapshot"].assert_called_once()
        mocks["get_performance_summary"].assert_called_once()
        mocks["get_all_sentiment"].assert_called_once()
        mocks["get_decision"].assert_called_once()
        mocks["send_daily_briefing"].assert_called_once()

    def test_snapshot_saved_before_sentiment(self):
        """save_snapshot must be called before get_all_sentiment."""
        call_order: list[str] = []

        mocks = _patch_pipeline()
        mocks["save_snapshot"]      = MagicMock(side_effect=lambda *a: call_order.append("snapshot"))
        mocks["get_all_sentiment"]  = MagicMock(side_effect=lambda *a: call_order.append("sentiment") or MOCK_SENTIMENT)

        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        assert call_order.index("snapshot") < call_order.index("sentiment")

    def test_sentiment_only_for_stock_tickers(self):
        """Only stock tickers (not crypto) are passed to get_all_sentiment."""
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        called_tickers = mocks["get_all_sentiment"].call_args.args[0]
        # All tickers passed should be stocks — i.e., none of the known crypto ids
        crypto_ids = {"bitcoin", "ethereum"}
        for t in called_tickers:
            assert t not in crypto_ids, f"Crypto ticker {t} should not be in sentiment call"

    def test_continues_after_sentiment_failure(self):
        """If sentiment raises, briefing still completes and sends."""
        mocks = _patch_pipeline(**{
            "main.get_all_sentiment": MagicMock(side_effect=Exception("API down")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        mocks["send_daily_briefing"].assert_called_once()

    def test_continues_after_snapshot_failure(self):
        mocks = _patch_pipeline(**{
            "main.save_snapshot": MagicMock(side_effect=Exception("disk full")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        # Pipeline should still reach send_daily_briefing
        mocks["send_daily_briefing"].assert_called_once()

    def test_continues_after_decision_failure(self):
        mocks = _patch_pipeline(**{
            "main.get_decision": MagicMock(side_effect=Exception("Claude down")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        mocks["send_daily_briefing"].assert_called_once()

    def test_returns_early_when_prices_fail(self):
        """If price fetch fails, nothing downstream is called."""
        mocks = _patch_pipeline(**{
            "main.get_all_prices": MagicMock(side_effect=Exception("no network")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        mocks["calculate_portfolio"].assert_not_called()
        mocks["send_daily_briefing"].assert_not_called()

    def test_returns_early_when_portfolio_calc_fails(self):
        mocks = _patch_pipeline(**{
            "main.calculate_portfolio": MagicMock(side_effect=Exception("bad data")),
        })
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        mocks["save_snapshot"].assert_not_called()
        mocks["send_daily_briefing"].assert_not_called()

    def test_decision_receives_portfolio_state_and_rules(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        args = mocks["get_decision"].call_args.args
        assert args[0] == MOCK_STATE   # portfolio_state
        assert args[1] == []            # triggered_rules (empty from mock)

    def test_send_daily_briefing_receives_decision_text(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_daily_briefing()

        kwargs = mocks["send_daily_briefing"].call_args
        # decision is second positional argument
        called_decision = kwargs.args[1] if kwargs.args else kwargs.kwargs.get("decision")
        assert called_decision == MOCK_DECISION


# ── run_weekly_digest ─────────────────────────────────────────


class TestRunWeeklyDigest:
    """run_weekly_digest sends digest when enough history exists."""

    def test_calls_send_weekly_digest_when_performance_available(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_weekly_digest()
        mocks["send_weekly_digest"].assert_called_once()

    def test_skips_digest_when_no_performance_data(self):
        mocks = _patch_pipeline(**{
            "main.get_performance_summary": MagicMock(return_value={}),
        })
        with patch.multiple("main", **mocks):
            main.run_weekly_digest()
        mocks["send_weekly_digest"].assert_not_called()

    def test_calls_get_all_prices_for_current_value(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_weekly_digest()
        mocks["get_all_prices"].assert_called_once()

    def test_does_not_raise_on_failure(self):
        mocks = _patch_pipeline(**{
            "main.get_all_prices": MagicMock(side_effect=Exception("network")),
        })
        with patch.multiple("main", **mocks):
            main.run_weekly_digest()  # must not raise

    def test_does_not_call_sentiment_or_decision(self):
        mocks = _patch_pipeline()
        with patch.multiple("main", **mocks):
            main.run_weekly_digest()
        mocks["get_all_sentiment"].assert_not_called()
        mocks["get_decision"].assert_not_called()
