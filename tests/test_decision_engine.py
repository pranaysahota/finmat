"""
Tests for modules/decision_engine.py — context building and Claude Sonnet decision generation.
All Anthropic API calls are mocked; no real network requests are made.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from modules.decision_engine import (
    _FALLBACK_DECISION,
    build_context,
    get_decision,
    get_stock_analysis,
)


# ── Shared test fixtures ──────────────────────────────────────

PORTFOLIO_STATE = {
    "total_value":    8200.00,
    "total_cost":     8000.00,
    "total_pnl_usd":  200.00,
    "total_pnl_pct":  2.50,
    "bucket_values":  {"Diversified": 4980.0, "Growth": 2010.0},
    "bucket_weights": {"Diversified": 71.2, "Growth": 28.8},
    "holdings": {
        "MSFT": {
            "current_price": 430.0, "current_value": 1290.0,
            "cost_basis": 1200.0,  "pnl_pct": 7.5,
            "pnl_usd": 90.0,       "bucket": "Diversified",
        },
        "NVDA": {
            "current_price": 140.0, "current_value": 700.0,
            "cost_basis": 675.0,   "pnl_pct": 3.7,
            "pnl_usd": 25.0,       "bucket": "Growth",
        },
    },
}

TRIGGERED_RULES = [
    {"level": "HIGH", "ticker": "MSFT", "rule": "take_profit",
     "message": "🟢 MSFT is up 7.5% — take-profit threshold reached (40%)"},
]

BUCKET_DRIFT = [
    {"level": "MEDIUM", "ticker": "Growth", "rule": "bucket_drift",
     "message": "📐 Growth bucket is underweight: 24.5% actual vs 25% target (drift: -0.5pp)"},
]

SENTIMENT = {
    "MSFT": {"score": 0.6, "label": "BULLISH", "summary": "Azure growth beats expectations."},
    "NVDA": {"score": 0.3, "label": "SLIGHTLY_BULLISH", "summary": "AI chip demand strong."},
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

WATCHLIST_STATE = {
    "total_value": 700.0,
    "total_cost": 675.0,
    "total_pnl_usd": 25.0,
    "total_pnl_pct": 3.7,
    "bucket_values": {"Growth": 700.0},
    "bucket_weights": {"Growth": 100.0},
    "holdings": {
        "NVDA": {
            "current_price": 140.0, "current_value": 700.0,
            "cost_basis": 675.0, "pnl_pct": 3.7,
            "pnl_usd": 25.0, "bucket": "Growth",
        },
        "TSLA": {
            "current_price": 250.0, "current_value": 0.0,
            "cost_basis": 0.0, "pnl_pct": 0.0,
            "pnl_usd": 0.0, "bucket": "Watchlist",
        },
    },
}


def _api_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    return msg


# ── build_context ─────────────────────────────────────────────


class TestBuildContext:
    """build_context formats portfolio data into a readable text block."""

    def test_returns_string(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert isinstance(ctx, str)

    def test_contains_portfolio_snapshot_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "PORTFOLIO SNAPSHOT" in ctx

    def test_total_value_in_context(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "8,200.00" in ctx

    def test_total_pnl_in_context(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "+200.00" in ctx

    def test_contains_bucket_breakdown_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "BUCKET BREAKDOWN" in ctx

    def test_all_buckets_appear_in_context(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        for bucket in ("Diversified", "Growth"):
            assert bucket in ctx

    def test_contains_holdings_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "HOLDINGS" in ctx

    def test_all_holdings_tickers_appear(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        for ticker in ("MSFT", "NVDA"):
            assert ticker in ctx

    def test_contains_triggered_rules_section(self):
        ctx = build_context(PORTFOLIO_STATE, TRIGGERED_RULES, [], {}, {}, {})
        assert "TRIGGERED RULES" in ctx

    def test_triggered_rule_message_appears(self):
        ctx = build_context(PORTFOLIO_STATE, TRIGGERED_RULES, [], {}, {}, {})
        assert "take-profit" in ctx.lower() or "take_profit" in ctx.lower() or "HIGH" in ctx

    def test_no_triggered_rules_shows_none(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "None triggered" in ctx

    def test_contains_bucket_drift_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], BUCKET_DRIFT, {}, {}, {})
        assert "BUCKET DRIFT" in ctx

    def test_no_drift_shows_within_targets(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "Within targets" in ctx

    def test_contains_sentiment_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, SENTIMENT, {})
        assert "SENTIMENT" in ctx

    def test_sentiment_labels_appear(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, SENTIMENT, {})
        assert "BULLISH" in ctx

    def test_sentiment_summaries_appear(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, SENTIMENT, {})
        assert "Azure growth" in ctx

    def test_empty_sentiment_shows_no_data(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "No sentiment data available" in ctx

    def test_contains_performance_section(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, PERFORMANCE)
        assert "PERFORMANCE HISTORY" in ctx

    def test_since_inception_pct_in_context(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, PERFORMANCE)
        assert "+2.50%" in ctx

    def test_last_7_days_pct_appears_when_available(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, PERFORMANCE)
        assert "Last 7 days" in ctx
        assert "+1.20%" in ctx

    def test_no_performance_shows_insufficient_history(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "Insufficient history" in ctx

    def test_best_worst_performers_appear(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, PERFORMANCE)
        assert "Best performer" in ctx
        assert "Worst performer" in ctx

    def test_7_days_none_shows_insufficient_data(self):
        perf_no_7day = dict(PERFORMANCE)
        perf_no_7day["last_7_days_pct"] = None
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, perf_no_7day)
        assert "insufficient data" in ctx.lower()

    def test_holding_pnl_pct_in_context(self):
        ctx = build_context(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "+7.5%" in ctx


# ── get_stock_analysis ───────────────────────────────────────


class TestGetStockAnalysis:
    """get_stock_analysis builds strict daily/weekly Gemini prompts."""

    def _capture_prompt(self, **kwargs) -> str:
        with patch("modules.decision_engine._get_gemini_client", return_value=MagicMock()):
            with patch("modules.decision_engine._gemini_generate", return_value="ok") as mock_generate:
                get_stock_analysis(WATCHLIST_STATE, PERFORMANCE, SENTIMENT, {}, **kwargs)
        return mock_generate.call_args.args[1]

    def test_daily_prompt_requires_daily_sections(self):
        prompt = self._capture_prompt(
            briefing_mode="daily",
            news_window_label="last 24 hours",
        )

        assert "last 24 hours" in prompt
        assert "Daily Recap:" in prompt
        assert "Analyst Consensus:" in prompt
        assert "Investment Thesis:" in prompt
        assert "Forward Outlook:" in prompt

    def test_weekly_prompt_requires_weekly_sections(self):
        prompt = self._capture_prompt(
            briefing_mode="weekly",
            news_window_label="last week",
        )

        assert "last week" in prompt
        assert "Weekly Recap:" in prompt
        assert "Analyst Consensus:" in prompt
        assert "Investment Thesis:" in prompt
        assert "Forward Outlook:" in prompt

    def test_watchlist_prompt_requires_entry_and_target_sections(self):
        prompt = self._capture_prompt(
            briefing_mode="daily",
            news_window_label="last 24 hours",
        )

        assert "Current Price / Analyst Target:" in prompt
        assert "Entry Watch:" in prompt
        assert "current price supplied below" in prompt
        assert "analyst consensus target price" in prompt
        assert "good entry point" in prompt
        assert "support/resistance" in prompt
        assert "TSLA (Watchlist)" in prompt
        assert "Current price: $250.00" in prompt


# ── get_decision ──────────────────────────────────────────────


class TestGetDecision:
    """get_decision calls Claude Sonnet and returns the response text."""

    MOCK_BRIEFING = (
        "MARKET MOOD: Markets are cautiously bullish.\n\n"
        "PORTFOLIO STATUS: Portfolio up 2.5% since inception.\n\n"
        "ACTIONS REQUIRED:\n- No action needed\n\n"
        "WATCH LIST:\n- Monitor NVDA earnings next week"
    )

    def test_returns_string_on_success(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(self.MOCK_BRIEFING)
            result = get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert isinstance(result, str)

    def test_returns_briefing_text(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(self.MOCK_BRIEFING)
            result = get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "MARKET MOOD" in result

    def test_correct_model_used(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        kwargs = mock_create.call_args.kwargs
        assert kwargs["model"] == "claude-sonnet-4-6"

    def test_max_tokens_is_2500(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        kwargs = mock_create.call_args.kwargs
        assert kwargs["max_tokens"] == 2500

    def test_system_prompt_contains_irish_tax(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        kwargs = mock_create.call_args.kwargs
        assert "Irish" in kwargs["system"] or "Ireland" in kwargs["system"]

    def test_context_passed_as_user_message(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        kwargs    = mock_create.call_args.kwargs
        user_msg  = kwargs["messages"][0]["content"]
        # context should contain portfolio data
        assert "PORTFOLIO SNAPSHOT" in user_msg

    def test_returns_fallback_on_api_exception(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = Exception("API error")
            result = get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert result == _FALLBACK_DECISION

    def test_fallback_does_not_raise(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.side_effect = RuntimeError("timeout")
            result = get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert isinstance(result, str)

    def test_response_is_stripped(self):
        padded = "  \n" + self.MOCK_BRIEFING + "\n  "
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = _api_response(padded)
            result = get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_all_data_sections_flow_into_api_call(self):
        """build_context is called with all six arguments — spot-check via triggered rules."""
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, TRIGGERED_RULES, BUCKET_DRIFT, {}, SENTIMENT, PERFORMANCE)
        kwargs   = mock_create.call_args.kwargs
        user_msg = kwargs["messages"][0]["content"]
        # Triggered rule and sentiment should appear in the context passed to Claude
        assert "TRIGGERED RULES" in user_msg
        assert "BULLISH" in user_msg

    def test_normal_mode_used_when_no_triggered_rules(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        assert "CGT IMPACT" not in mock_create.call_args.kwargs["system"]

    def test_normal_mode_used_when_only_medium_rule_triggered(self):
        medium_rule = [{"level": "MEDIUM", "ticker": "Growth", "rule": "bucket_drift",
                        "message": "Growth drifted"}]
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, medium_rule, [], {}, {}, {})
        assert "CGT IMPACT" not in mock_create.call_args.kwargs["system"]

    def test_alert_mode_used_when_high_rule_triggered(self):
        # TRIGGERED_RULES fixture has level "HIGH"
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, TRIGGERED_RULES, [], {}, {}, {})
        assert "CGT IMPACT" in mock_create.call_args.kwargs["system"]

    def test_alert_mode_used_when_critical_rule_triggered(self):
        critical_rule = [{"level": "CRITICAL", "ticker": "NVDA", "rule": "stop_loss",
                          "message": "NVDA stop-loss hit"}]
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, critical_rule, [], {}, {}, {})
        assert "CGT IMPACT" in mock_create.call_args.kwargs["system"]

    def test_normal_prompt_instructs_no_cgt_commentary(self):
        with patch("modules.decision_engine.anthropic.Anthropic") as MockClient:
            mock_create = MockClient.return_value.messages.create
            mock_create.return_value = _api_response(self.MOCK_BRIEFING)
            get_decision(PORTFOLIO_STATE, [], [], {}, {}, {})
        system = mock_create.call_args.kwargs["system"]
        assert "Do not comment on CGT" in system
