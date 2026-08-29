"""
Tests for modules/portfolio.py — calculate_portfolio, check_rules, check_bucket_drift.

PORTFOLIO, RULES, and BUCKET_TARGETS are monkeypatched to isolated fixtures
so tests never depend on the real portfolio/local.py values.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.portfolio as portfolio_mod
from modules.portfolio import calculate_portfolio, check_bucket_drift, check_rules


# ── Shared fixtures ───────────────────────────────────────────

# Clean portfolio with round numbers for easy manual verification
MOCK_PORTFOLIO = {
    "Diversified": {
        "MSFT": {"type": "stock",  "qty": 2.0,   "avg_buy": 100.00,
                 "allocation_usd": 0, "bucket_pct": 0},
        "JNJ":  {"type": "stock",  "qty": 4.0,   "avg_buy": 50.00,
                 "allocation_usd": 0, "bucket_pct": 0},
    },
    "Growth": {
        "NVDA": {"type": "stock",  "qty": 4.0,   "avg_buy": 50.00,
                 "allocation_usd": 0, "bucket_pct": 0},
    },
    "Crypto": {
        "bitcoin": {"type": "crypto", "qty": 0.01, "avg_buy": 80000.00,
                    "allocation_usd": 0, "bucket_pct": 0},
    },
}

# Prices that give clean arithmetic:
#   MSFT:    2.0  × 120  = 240   cost 200   pnl +40   (+20%)
#   JNJ:     4.0  × 50   = 200   cost 200   pnl   0   (  0%)
#   NVDA:    4.0  × 60   = 240   cost 200   pnl +40   (+20%)
#   bitcoin: 0.01 × 100k = 1000  cost 800   pnl +200  (+25%)
#   total_value = 1680,  total_cost = 1400,  pnl = 280 (+20%)
MOCK_PRICES = {
    "MSFT":    120.00,
    "JNJ":      50.00,
    "NVDA":     60.00,
    "bitcoin": 100000.00,
}

MOCK_RULES = {
    "stop_loss_pct":    -20,
    "take_profit_pct":   40,
    "crypto_max_weight": 20,
    "bucket_drift_pct":   5,
    "benchmark":       "MSFT",
}

MOCK_TARGETS = {"Diversified": 60, "Growth": 25, "Crypto": 15}


@pytest.fixture(autouse=True)
def patch_module_globals(monkeypatch):
    monkeypatch.setattr(portfolio_mod, "PORTFOLIO",               MOCK_PORTFOLIO)
    monkeypatch.setattr(portfolio_mod, "RULES",                   MOCK_RULES)
    monkeypatch.setattr(portfolio_mod, "BUCKET_TARGETS",          MOCK_TARGETS)
    monkeypatch.setattr(portfolio_mod, "CRYPTO_ACTIVE",           True)


# ── calculate_portfolio ───────────────────────────────────────

class TestCalculatePortfolio:

    def test_returns_all_required_top_level_keys(self):
        state = calculate_portfolio(MOCK_PRICES)
        for key in ("total_value", "total_cost", "total_pnl_usd", "total_pnl_pct",
                    "crypto_weight", "bucket_values", "bucket_weights", "holdings"):
            assert key in state, f"Missing key: {key}"

    def test_holdings_contain_all_priced_tickers(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert set(state["holdings"].keys()) == set(MOCK_PRICES.keys())

    def test_holdings_contain_required_per_ticker_keys(self):
        state = calculate_portfolio(MOCK_PRICES)
        for ticker, data in state["holdings"].items():
            for key in ("current_price", "current_value", "cost_basis",
                        "pnl_pct", "pnl_usd", "bucket"):
                assert key in data, f"{ticker} missing key: {key}"

    def test_current_value_is_qty_times_price(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert state["holdings"]["MSFT"]["current_value"] == round(2.0 * 120.00, 2)
        assert state["holdings"]["NVDA"]["current_value"] == round(4.0 * 60.00,  2)

    def test_cost_basis_is_qty_times_avg_buy(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert state["holdings"]["MSFT"]["cost_basis"] == round(2.0 * 100.00, 2)
        assert state["holdings"]["JNJ"]["cost_basis"]  == round(4.0 *  50.00, 2)

    def test_pnl_usd_is_value_minus_cost(self):
        state = calculate_portfolio(MOCK_PRICES)
        h = state["holdings"]["MSFT"]
        assert h["pnl_usd"] == round(h["current_value"] - h["cost_basis"], 2)

    def test_pnl_pct_calculated_correctly(self):
        state = calculate_portfolio(MOCK_PRICES)
        # MSFT: (240-200)/200*100 = 20%
        assert state["holdings"]["MSFT"]["pnl_pct"] == 20.0
        # bitcoin: (1000-800)/800*100 = 25%
        assert state["holdings"]["bitcoin"]["pnl_pct"] == 25.0

    def test_zero_qty_excluded_from_holdings(self):
        """qty=0 positions (sold) are excluded from portfolio state entirely."""
        portfolio_with_zero = {
            "Diversified": {
                "MSFT": {"type": "stock", "qty": 0, "avg_buy": 0.0,
                         "allocation_usd": 0, "bucket_pct": 0},
            },
            "Growth":  {},
            "Crypto":  {},
        }
        import modules.portfolio as pm
        pm.PORTFOLIO = portfolio_with_zero
        state = calculate_portfolio({"MSFT": 120.00})
        assert "MSFT" not in state["holdings"]

    def test_ticker_with_none_price_excluded_from_holdings(self):
        prices_with_missing = {**MOCK_PRICES, "JNJ": None}
        state = calculate_portfolio(prices_with_missing)
        assert "JNJ" not in state["holdings"]
        assert "MSFT" in state["holdings"]

    def test_none_price_prints_warning(self, capsys):
        calculate_portfolio({**MOCK_PRICES, "JNJ": None})
        assert "JNJ" in capsys.readouterr().out

    def test_total_value_is_sum_of_holding_values(self):
        state = calculate_portfolio(MOCK_PRICES)
        expected = round(sum(h["current_value"] for h in state["holdings"].values()), 2)
        assert state["total_value"] == expected
        assert state["invested_value"] == expected

    def test_cash_balance_increases_total_value_without_changing_pnl_or_weights(self):
        state = calculate_portfolio(MOCK_PRICES, cash_balance=320.0)

        assert state["invested_value"] == 1680.00
        assert state["cash_balance"] == 320.00
        assert state["total_value"] == 2000.00
        assert state["total_cost"] == 1400.00
        assert state["total_pnl_usd"] == 280.00
        assert state["total_pnl_pct"] == 20.0
        assert state["bucket_values"]["Diversified"] == 440.00
        assert state["bucket_weights"]["Diversified"] == round(440 / 1680 * 100, 2)

    def test_total_cost_is_sum_of_cost_bases(self):
        state = calculate_portfolio(MOCK_PRICES)
        expected = round(sum(h["cost_basis"] for h in state["holdings"].values()), 2)
        assert state["total_cost"] == expected

    def test_total_pnl_usd_is_value_minus_cost(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert state["total_pnl_usd"] == round(state["total_value"] - state["total_cost"], 2)

    def test_total_pnl_pct_calculated_correctly(self):
        state = calculate_portfolio(MOCK_PRICES)
        # total_value=1680, total_cost=1400, pnl=280, pct=20%
        assert state["total_value"]   == 1680.00
        assert state["total_cost"]    == 1400.00
        assert state["total_pnl_usd"] == 280.00
        assert state["total_pnl_pct"] == round(280 / 1400 * 100, 2)

    def test_bucket_values_summed_per_bucket(self):
        state = calculate_portfolio(MOCK_PRICES)
        # Diversified: MSFT(240) + JNJ(200) = 440
        assert state["bucket_values"]["Diversified"] == 440.00
        assert state["bucket_values"]["Growth"]      == 240.00
        assert state["bucket_values"]["Crypto"]      == 1000.00

    def test_bucket_weights_sum_to_100(self):
        state = calculate_portfolio(MOCK_PRICES)
        total = sum(state["bucket_weights"].values())
        assert abs(total - 100.0) < 0.1   # allow for float rounding

    def test_bucket_weights_proportional_to_values(self):
        state = calculate_portfolio(MOCK_PRICES)
        # Diversified = 440/1680 ≈ 26.19%
        expected = round(440 / 1680 * 100, 2)
        assert state["bucket_weights"]["Diversified"] == expected

    def test_crypto_weight_matches_crypto_bucket_weight(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert state["crypto_weight"] == state["bucket_weights"]["Crypto"]

    def test_crypto_weight_is_zero_when_no_crypto_value(self):
        portfolio_no_crypto = {
            "Diversified": MOCK_PORTFOLIO["Diversified"],
            "Growth":      MOCK_PORTFOLIO["Growth"],
            "Crypto":      {"bitcoin": {"type": "crypto", "qty": 0, "avg_buy": 0.0,
                                        "allocation_usd": 0, "bucket_pct": 0}},
        }
        import modules.portfolio as pm
        pm.PORTFOLIO = portfolio_no_crypto
        state = calculate_portfolio({"MSFT": 120.00, "JNJ": 50.00, "NVDA": 60.00, "bitcoin": 100000.00})
        assert state["crypto_weight"] == 0.0

    def test_holding_bucket_field_correct(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert state["holdings"]["MSFT"]["bucket"]    == "Diversified"
        assert state["holdings"]["NVDA"]["bucket"]    == "Growth"
        assert state["holdings"]["bitcoin"]["bucket"] == "Crypto"

    def test_all_monetary_values_rounded_to_2dp(self):
        state = calculate_portfolio(MOCK_PRICES)
        for field in ("total_value", "total_cost", "total_pnl_usd"):
            val = state[field]
            assert val == round(val, 2), f"{field} not rounded to 2dp"
        for ticker, data in state["holdings"].items():
            for field in ("current_value", "cost_basis", "pnl_usd"):
                val = data[field]
                assert val == round(val, 2), f"{ticker}/{field} not rounded to 2dp"

    def test_empty_prices_returns_zero_state(self):
        state = calculate_portfolio({})
        assert state["total_value"]   == 0.0
        assert state["total_cost"]    == 0.0
        assert state["total_pnl_pct"] == 0.0
        assert state["crypto_weight"] == 0.0
        assert state["holdings"]      == {}


# ── check_rules ───────────────────────────────────────────────

class TestCheckRules:

    def _state(self, holdings: dict, crypto_weight: float = 0.0) -> dict:
        """Build a minimal portfolio_state for rule-checking tests."""
        return {
            "total_value":    1000.0,
            "total_cost":     1000.0,
            "total_pnl_usd":  0.0,
            "total_pnl_pct":  0.0,
            "crypto_weight":  crypto_weight,
            "bucket_values":  {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "bucket_weights": {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "holdings":       holdings,
        }

    def _holding(self, pnl_pct: float) -> dict:
        return {
            "current_price": 100.0,
            "current_value": 100.0,
            "cost_basis":    100.0,
            "pnl_pct":       pnl_pct,
            "pnl_usd":       0.0,
            "bucket":        "Diversified",
        }

    def test_returns_empty_list_when_nothing_triggered(self):
        state = self._state({"MSFT": self._holding(5.0)})
        assert check_rules(state) == []

    def test_stop_loss_triggers_at_threshold(self):
        state = self._state({"MSFT": self._holding(-20.0)})   # exactly at -20
        alerts = check_rules(state)
        assert any(a["rule"] == "stop_loss" for a in alerts)

    def test_stop_loss_triggers_below_threshold(self):
        state = self._state({"MSFT": self._holding(-25.0)})
        alerts = check_rules(state)
        assert any(a["rule"] == "stop_loss" for a in alerts)

    def test_stop_loss_level_is_critical(self):
        state = self._state({"MSFT": self._holding(-20.0)})
        alert = next(a for a in check_rules(state) if a["rule"] == "stop_loss")
        assert alert["level"] == "CRITICAL"

    def test_stop_loss_ticker_in_alert(self):
        state = self._state({"NVDA": self._holding(-30.0)})
        alert = next(a for a in check_rules(state) if a["rule"] == "stop_loss")
        assert alert["ticker"] == "NVDA"

    def test_take_profit_triggers_at_threshold(self):
        state = self._state({"MSFT": self._holding(40.0)})    # exactly at +40
        alerts = check_rules(state)
        assert any(a["rule"] == "take_profit" for a in alerts)

    def test_take_profit_triggers_above_threshold(self):
        state = self._state({"MSFT": self._holding(55.0)})
        alerts = check_rules(state)
        assert any(a["rule"] == "take_profit" for a in alerts)

    def test_take_profit_level_is_high(self):
        state = self._state({"MSFT": self._holding(40.0)})
        alert = next(a for a in check_rules(state) if a["rule"] == "take_profit")
        assert alert["level"] == "HIGH"

    def test_between_thresholds_no_alert(self):
        state = self._state({"MSFT": self._holding(-19.9)})
        assert check_rules(state) == []

    def test_crypto_weight_triggers_strictly_above_limit(self):
        state = self._state({}, crypto_weight=20.1)
        alerts = check_rules(state)
        assert any(a["rule"] == "crypto_weight" for a in alerts)

    def test_crypto_weight_does_not_trigger_at_exactly_limit(self):
        """Rule is crypto_weight > limit, so equality should not trigger."""
        state = self._state({}, crypto_weight=20.0)
        assert not any(a["rule"] == "crypto_weight" for a in check_rules(state))

    def test_crypto_weight_level_is_medium(self):
        state = self._state({}, crypto_weight=21.0)
        alert = next(a for a in check_rules(state) if a["rule"] == "crypto_weight")
        assert alert["level"] == "MEDIUM"

    def test_crypto_weight_ticker_is_crypto(self):
        state = self._state({}, crypto_weight=21.0)
        alert = next(a for a in check_rules(state) if a["rule"] == "crypto_weight")
        assert alert["ticker"] == "Crypto"

    def test_benchmark_does_not_trigger_an_alert(self):
        """MSFT is the benchmark — being up or down does not fire a benchmark alert."""
        state = self._state({"MSFT": self._holding(10.0)})
        alerts = check_rules(state)
        assert not any(a.get("rule") == "benchmark" for a in alerts)

    def test_multiple_holdings_can_trigger_multiple_alerts(self):
        state = self._state({
            "MSFT": self._holding(-25.0),
            "NVDA": self._holding(-21.0),
        })
        alerts = check_rules(state)
        assert len(alerts) == 2

    def test_alert_has_required_keys(self):
        state = self._state({"MSFT": self._holding(-25.0)})
        alert = check_rules(state)[0]
        for key in ("level", "ticker", "rule", "message"):
            assert key in alert

    def test_stop_loss_and_take_profit_are_mutually_exclusive_per_ticker(self):
        """A ticker cannot fire both stop_loss and take_profit simultaneously."""
        state = self._state({"MSFT": self._holding(-25.0)})
        rules = [a["rule"] for a in check_rules(state) if a["ticker"] == "MSFT"]
        assert len(rules) == 1
        assert "stop_loss" in rules


# ── check_bucket_drift ────────────────────────────────────────

class TestCheckBucketDrift:

    def _state(self, bucket_weights: dict) -> dict:
        return {
            "total_value":    1000.0,
            "total_cost":     1000.0,
            "total_pnl_usd":  0.0,
            "total_pnl_pct":  0.0,
            "crypto_weight":  bucket_weights.get("Crypto", 0.0),
            "bucket_values":  {b: 0.0 for b in bucket_weights},
            "bucket_weights": bucket_weights,
            "holdings":       {},
        }

    def test_no_alerts_when_all_buckets_on_target(self):
        state = self._state({"Diversified": 60.0, "Growth": 25.0, "Crypto": 15.0})
        assert check_bucket_drift(state) == []

    def test_no_alerts_when_drift_within_threshold(self):
        # Drift of exactly 5pp — rule is > 5, not >= 5
        state = self._state({"Diversified": 55.0, "Growth": 25.0, "Crypto": 20.0})
        assert check_bucket_drift(state) == []

    def test_alert_when_overweight_beyond_threshold(self):
        # Growth at 32% vs target 25% → drift +7pp
        state = self._state({"Diversified": 60.0, "Growth": 32.0, "Crypto": 8.0})
        alerts = check_bucket_drift(state)
        assert any(a["ticker"] == "Growth" for a in alerts)

    def test_alert_when_underweight_beyond_threshold(self):
        # Diversified at 50% vs target 60% → drift -10pp
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        alerts = check_bucket_drift(state)
        assert any(a["ticker"] == "Diversified" for a in alerts)

    def test_alert_level_is_medium(self):
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        for alert in check_bucket_drift(state):
            assert alert["level"] == "MEDIUM"

    def test_alert_rule_field_is_bucket_drift(self):
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        for alert in check_bucket_drift(state):
            assert alert["rule"] == "bucket_drift"

    def test_alert_message_contains_bucket_name(self):
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        alert = next(a for a in check_bucket_drift(state) if a["ticker"] == "Diversified")
        assert "Diversified" in alert["message"]

    def test_overweight_direction_in_message(self):
        state = self._state({"Diversified": 60.0, "Growth": 32.0, "Crypto": 8.0})
        alert = next(a for a in check_bucket_drift(state) if a["ticker"] == "Growth")
        assert "overweight" in alert["message"]

    def test_underweight_direction_in_message(self):
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        alert = next(a for a in check_bucket_drift(state) if a["ticker"] == "Diversified")
        assert "underweight" in alert["message"]

    def test_multiple_drifting_buckets_return_multiple_alerts(self):
        # Both Diversified and Growth drifting > 5pp
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        alerts = check_bucket_drift(state)
        assert len(alerts) == 2

    def test_alert_has_required_keys(self):
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        alert = check_bucket_drift(state)[0]
        for key in ("level", "ticker", "rule", "message"):
            assert key in alert

    def test_uses_rules_bucket_drift_pct_threshold(self, monkeypatch):
        """Changing the threshold in RULES changes when alerts fire."""
        monkeypatch.setattr(portfolio_mod, "RULES", {**MOCK_RULES, "bucket_drift_pct": 15})
        # Drift of 10pp — below new threshold of 15, so no alert
        state = self._state({"Diversified": 50.0, "Growth": 35.0, "Crypto": 15.0})
        assert check_bucket_drift(state) == []


# ── CRYPTO_ACTIVE = False ─────────────────────────────────────


class TestCryptoInactive:
    """Tests for CRYPTO_ACTIVE = False — crypto bucket excluded from all calculations."""

    @pytest.fixture(autouse=True)
    def set_crypto_inactive(self, monkeypatch):
        monkeypatch.setattr(portfolio_mod, "CRYPTO_ACTIVE", False)

    def test_crypto_tickers_absent_from_holdings(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert "bitcoin" not in state["holdings"]

    def test_crypto_bucket_absent_from_bucket_values(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert "Crypto" not in state["bucket_values"]

    def test_crypto_bucket_absent_from_bucket_weights(self):
        state = calculate_portfolio(MOCK_PRICES)
        assert "Crypto" not in state["bucket_weights"]

    def test_bucket_weights_sum_to_100_without_crypto(self):
        state = calculate_portfolio(MOCK_PRICES)
        total = sum(state["bucket_weights"].values())
        assert abs(total - 100.0) < 0.1

    def test_total_value_excludes_crypto(self):
        # With CRYPTO_ACTIVE=False: MSFT(240)+JNJ(200)+NVDA(240)=680, no bitcoin(1000)
        state = calculate_portfolio(MOCK_PRICES)
        assert state["total_value"] == 680.00

    def test_check_rules_skips_crypto_weight_alert(self):
        state = calculate_portfolio(MOCK_PRICES)
        # Force crypto_weight high — should not trigger when CRYPTO_ACTIVE=False
        state["crypto_weight"] = 99.0
        alerts = check_rules(state)
        assert not any(a["rule"] == "crypto_weight" for a in alerts)

    def test_check_bucket_drift_no_crypto_alert(self):
        state = calculate_portfolio(MOCK_PRICES)
        alerts = check_bucket_drift(state)
        assert not any(a["ticker"] == "Crypto" for a in alerts)

    def test_check_bucket_drift_uses_adjusted_diversified_target(self):
        # With MOCK_PRICES and CRYPTO_ACTIVE=False:
        #   total_value=680, Diversified=440 (64.7%), Growth=240 (35.3%)
        #   Adjusted target: Diversified=70.6% → drift=-5.9pp → alert fires
        state = calculate_portfolio(MOCK_PRICES)
        alerts = check_bucket_drift(state)
        div_alert = next((a for a in alerts if a["ticker"] == "Diversified"), None)
        assert div_alert is not None, "Expected Diversified drift alert"
        assert "70.6" in div_alert["message"]

    def test_check_bucket_drift_uses_adjusted_growth_target(self):
        state = calculate_portfolio(MOCK_PRICES)
        alerts = check_bucket_drift(state)
        growth_alert = next((a for a in alerts if a["ticker"] == "Growth"), None)
        assert growth_alert is not None, "Expected Growth drift alert"
        assert "29.4" in growth_alert["message"]
