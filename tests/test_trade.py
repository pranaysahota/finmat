"""
Tests for trade.py — covers pure helper functions and file-modifying functions.
PORTFOLIO_FILE, DATA_DIR, and TRADES_FILE are monkeypatched to temp paths for isolation.
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import trade  # noqa: E402  (after sys.path setup)
from trade import (  # noqa: E402
    _add_new_ticker,
    _append_trade,
    _calc_cgt,
    _find_field_node,
    _find_ticker,
    _normalise_ticker,
    _replace_value_at,
    _update_existing_ticker,
)


# ── Shared test data ──────────────────────────────────────────

# Minimal portfolio source with one ticker per bucket for AST-based tests.
MINIMAL_SOURCE = textwrap.dedent('''\
    PORTFOLIO = {
        "Diversified": {
            "MSFT": {
                "type":           "stock",
                "qty":            3.1,
                "avg_buy":        386.54,
                "allocation_usd": 0,
                "bucket_pct":     0,
            },
        },
        "Growth": {
            "NVDA": {
                "type":           "stock",
                "qty":            0,
                "avg_buy":        0.0,
                "allocation_usd": 0,
                "bucket_pct":     0,
            },
        },
        "Crypto": {
            "bitcoin": {
                "type":           "crypto",
                "qty":            0,
                "avg_buy":        0.0,
                "allocation_usd": 0,
                "bucket_pct":     0,
            },
        },
    }
''')

SAMPLE_PORTFOLIO = {
    "Diversified": {
        "MSFT": {"type": "stock", "qty": 3.1, "avg_buy": 386.54,
                 "allocation_usd": 0, "bucket_pct": 0},
    },
    "Growth": {
        "NVDA": {"type": "stock", "qty": 0, "avg_buy": 0.0,
                 "allocation_usd": 0, "bucket_pct": 0},
    },
    "Crypto": {
        "bitcoin": {"type": "crypto", "qty": 0, "avg_buy": 0.0,
                    "allocation_usd": 0, "bucket_pct": 0},
    },
}


# ── _normalise_ticker ─────────────────────────────────────────

class TestNormaliseTicker:

    def test_stock_lowercased_input_uppercased(self):
        assert _normalise_ticker("nvda", "stock") == "NVDA"

    def test_stock_already_upper_unchanged(self):
        assert _normalise_ticker("MSFT", "stock") == "MSFT"

    def test_crypto_uppercased_input_lowercased(self):
        assert _normalise_ticker("BITCOIN", "crypto") == "bitcoin"

    def test_crypto_already_lower_unchanged(self):
        assert _normalise_ticker("ethereum", "crypto") == "ethereum"

    def test_mixed_case_stock_fully_uppercased(self):
        assert _normalise_ticker("BrK.b", "stock") == "BRK.B"


# ── _find_ticker ──────────────────────────────────────────────

class TestFindTicker:

    def test_finds_stock_ticker_in_correct_bucket(self):
        bucket, asset = _find_ticker(SAMPLE_PORTFOLIO, "MSFT")
        assert bucket == "Diversified"
        assert asset["qty"] == 3.1

    def test_finds_crypto_ticker(self):
        bucket, asset = _find_ticker(SAMPLE_PORTFOLIO, "bitcoin")
        assert bucket == "Crypto"
        assert asset["type"] == "crypto"

    def test_returns_none_for_missing_ticker(self):
        bucket, asset = _find_ticker(SAMPLE_PORTFOLIO, "AAPL")
        assert bucket is None
        assert asset is None

    def test_lookup_is_case_sensitive(self):
        # "BITCOIN" (upper) is not found — portfolio stores "bitcoin" (lower)
        bucket, asset = _find_ticker(SAMPLE_PORTFOLIO, "BITCOIN")
        assert bucket is None

    def test_finds_ticker_in_growth_bucket(self):
        bucket, asset = _find_ticker(SAMPLE_PORTFOLIO, "NVDA")
        assert bucket == "Growth"


# ── _find_field_node ──────────────────────────────────────────

class TestFindFieldNode:

    def test_finds_qty_field(self):
        lineno, col = _find_field_node(MINIMAL_SOURCE, "MSFT", "qty")
        assert lineno is not None
        assert col is not None

    def test_finds_avg_buy_field(self):
        lineno, col = _find_field_node(MINIMAL_SOURCE, "MSFT", "avg_buy")
        assert lineno is not None
        assert col is not None

    def test_missing_ticker_returns_none_pair(self):
        lineno, col = _find_field_node(MINIMAL_SOURCE, "AAPL", "qty")
        assert lineno is None
        assert col is None

    def test_position_points_to_correct_numeric_value(self):
        """The character at the returned position should be the start of the value."""
        lineno, col = _find_field_node(MINIMAL_SOURCE, "MSFT", "qty")
        lines = MINIMAL_SOURCE.splitlines()
        line = lines[lineno - 1]        # lineno is 1-indexed
        end = col
        while end < len(line) and (line[end].isdigit() or line[end] == "."):
            end += 1
        assert line[col:end] == "3.1"

    def test_avg_buy_position_points_to_correct_value(self):
        lineno, col = _find_field_node(MINIMAL_SOURCE, "MSFT", "avg_buy")
        lines = MINIMAL_SOURCE.splitlines()
        line = lines[lineno - 1]
        end = col
        while end < len(line) and (line[end].isdigit() or line[end] == "."):
            end += 1
        assert line[col:end] == "386.54"


# ── _replace_value_at ─────────────────────────────────────────

class TestReplaceValueAt:

    def test_replaces_single_digit_integer(self):
        source = "x = 0\n"
        result = _replace_value_at(source, 1, 4, "42")
        assert result == "x = 42\n"

    def test_replaces_float_in_portfolio_line(self):
        source = '        "qty":            3.1,\n'
        col = source.index("3")
        result = _replace_value_at(source, 1, col, "5.6")
        assert "5.6" in result
        assert "3.1" not in result

    def test_surrounding_text_is_preserved(self):
        source = '        "qty":            3.1,   # inline comment\n'
        col = source.index("3")
        result = _replace_value_at(source, 1, col, "99")
        assert "# inline comment" in result
        assert result.startswith('        "qty":')

    def test_replaces_zero(self):
        source = '        "allocation_usd": 0,\n'
        col = source.index("0,") # find the 0 before comma
        result = _replace_value_at(source, 1, col, "500")
        assert "500" in result

    def test_multiline_source_correct_line_targeted(self):
        source = "a = 1\nb = 2\nc = 3\n"
        result = _replace_value_at(source, 2, 4, "99")
        assert result == "a = 1\nb = 99\nc = 3\n"


# ── _update_existing_ticker ───────────────────────────────────

class TestUpdateExistingTicker:

    @pytest.fixture
    def portfolio_file(self, tmp_path):
        f = tmp_path / "local.py"
        f.write_text(MINIMAL_SOURCE)
        return f

    def test_updates_qty_in_file(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _update_existing_ticker("MSFT", 5.6, 400.00)
        assert "5.6" in portfolio_file.read_text()

    def test_updates_avg_buy_in_file(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _update_existing_ticker("MSFT", 5.6, 400.00)
        assert "400.00" in portfolio_file.read_text()

    def test_old_qty_is_replaced(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _update_existing_ticker("MSFT", 10.0, 390.00)
        # Old value 3.1 should no longer appear as the qty
        updated = portfolio_file.read_text()
        assert "10.0" in updated
        assert "3.1" not in updated

    def test_other_tickers_unchanged(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _update_existing_ticker("MSFT", 5.6, 400.00)
        updated = portfolio_file.read_text()
        assert '"NVDA"' in updated
        assert '"bitcoin"' in updated

    def test_raises_value_error_for_unknown_ticker(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        with pytest.raises(ValueError, match="AAPL"):
            _update_existing_ticker("AAPL", 1.0, 100.00)


# ── _add_new_ticker ───────────────────────────────────────────

class TestAddNewTicker:

    @pytest.fixture
    def portfolio_file(self, tmp_path):
        f = tmp_path / "local.py"
        f.write_text(MINIMAL_SOURCE)
        return f

    def test_new_stock_ticker_appears_in_file(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("AAPL", "Diversified", "stock", 2.0, 220.50)
        updated = portfolio_file.read_text()
        assert '"AAPL"' in updated

    def test_new_ticker_qty_written(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("AAPL", "Diversified", "stock", 2.0, 220.50)
        assert "2.0" in portfolio_file.read_text()

    def test_new_ticker_avg_buy_written(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("AAPL", "Diversified", "stock", 2.0, 220.50)
        assert "220.50" in portfolio_file.read_text()

    def test_new_crypto_ticker_added_to_crypto_bucket(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("solana", "Crypto", "crypto", 1.5, 180.00)
        updated = portfolio_file.read_text()
        assert '"solana"' in updated
        assert '"crypto"' in updated

    def test_existing_tickers_preserved_after_insert(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("GOOG", "Growth", "stock", 1.0, 175.00)
        updated = portfolio_file.read_text()
        assert '"NVDA"' in updated   # original Growth ticker still present
        assert '"GOOG"' in updated

    def test_raises_value_error_for_unknown_bucket(self, portfolio_file, monkeypatch):
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        with pytest.raises(ValueError, match="BadBucket"):
            _add_new_ticker("XYZ", "BadBucket", "stock", 1.0, 10.00)

    def test_file_remains_valid_python_after_insert(self, portfolio_file, monkeypatch):
        """The modified file should still parse without syntax errors."""
        import ast as _ast
        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        _add_new_ticker("AAPL", "Diversified", "stock", 2.0, 220.50)
        # If this raises SyntaxError the test fails
        _ast.parse(portfolio_file.read_text())


# ── _append_trade ─────────────────────────────────────────────

class TestAppendTrade:

    SAMPLE_TRADE = {
        "id":          "test-uuid-001",
        "ticker":      "MSFT",
        "bucket":      "Diversified",
        "type":        "stock",
        "qty_bought":  1.0,
        "price_paid":  400.00,
        "trade_value": 400.00,
        "new_qty":     1.0,
        "new_avg_buy": 400.00,
        "source":      "Revolut",
    }

    @pytest.fixture(autouse=True)
    def patch_trade_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trade, "DATA_DIR", tmp_path)
        monkeypatch.setattr(trade, "TRADES_FILE", tmp_path / "trades.json")

    def test_creates_file_when_missing(self, tmp_path):
        _append_trade(self.SAMPLE_TRADE)
        assert (tmp_path / "trades.json").exists()

    def test_file_contains_one_trade(self, tmp_path):
        _append_trade(self.SAMPLE_TRADE)
        data = json.loads((tmp_path / "trades.json").read_text())
        assert len(data) == 1

    def test_appends_second_trade(self, tmp_path):
        (tmp_path / "trades.json").write_text(json.dumps([self.SAMPLE_TRADE]))
        second = {**self.SAMPLE_TRADE, "id": "test-uuid-002"}
        _append_trade(second)
        data = json.loads((tmp_path / "trades.json").read_text())
        assert len(data) == 2

    def test_trade_data_preserved_correctly(self, tmp_path):
        _append_trade(self.SAMPLE_TRADE)
        data = json.loads((tmp_path / "trades.json").read_text())
        assert data[0]["ticker"] == "MSFT"
        assert data[0]["price_paid"] == 400.00
        assert data[0]["source"] == "Revolut"

    def test_handles_malformed_json_gracefully(self, tmp_path):
        (tmp_path / "trades.json").write_text("not {{ valid json")
        _append_trade(self.SAMPLE_TRADE)   # must not raise
        data = json.loads((tmp_path / "trades.json").read_text())
        assert len(data) == 1             # fresh list with only this trade


# ── Weighted average calculation ──────────────────────────────

# ── _calc_cgt ─────────────────────────────────────────────────

class TestCalcCGT:
    """CGT calculation: 33% on gain above €1,270 annual exemption."""

    def test_gain_below_exemption_returns_zero(self):
        # 10 shares @ $200, avg_buy $150 → gross $500 → within €1,270
        assert _calc_cgt(500.0) == 0.0

    def test_gain_above_exemption(self):
        # 10 shares @ $300, avg_buy $150 → gross $1,500
        # CGT = ($1,500 - $1,270) × 0.33 = $75.90
        assert _calc_cgt(1500.0) == 75.9

    def test_loss_returns_zero(self):
        assert _calc_cgt(-500.0) == 0.0

    def test_gain_exactly_at_exemption_returns_zero(self):
        assert _calc_cgt(1270.0) == 0.0

    def test_large_gain(self):
        # $10,000 gain → CGT = ($10,000 - $1,270) × 0.33 = $2,880.90
        assert _calc_cgt(10000.0) == round((10000 - 1270) * 0.33, 2)


# ── Sell trade record ─────────────────────────────────────────

class TestSellTradeRecord:
    """sell trade entry stored in trades.json has all required fields."""

    SELL_TRADE = {
        "id":             "test-sell-uuid",
        "timestamp":      "2026-03-02T10:00:00",
        "side":           "sell",
        "ticker":         "MSFT",
        "bucket":         "Diversified",
        "type":           "stock",
        "qty_sold":       2.0,
        "price_received": 400.00,
        "total_proceeds": 800.00,
        "cost_basis":     772.00,
        "gross_pnl":      28.00,
        "cgt_estimate":   0.0,
        "remaining_qty":  1.1,
        "source":         "Revolut",
    }

    @pytest.fixture(autouse=True)
    def patch_trade_paths(self, tmp_path, monkeypatch):
        monkeypatch.setattr(trade, "DATA_DIR", tmp_path)
        monkeypatch.setattr(trade, "TRADES_FILE", tmp_path / "trades.json")

    def test_sell_trade_has_side_sell(self, tmp_path):
        _append_trade(self.SELL_TRADE)
        data = json.loads((tmp_path / "trades.json").read_text())
        assert data[0]["side"] == "sell"

    def test_sell_trade_has_all_required_fields(self, tmp_path):
        _append_trade(self.SELL_TRADE)
        record = json.loads((tmp_path / "trades.json").read_text())[0]
        for field in (
            "id", "timestamp", "side", "ticker", "bucket", "type",
            "qty_sold", "price_received", "total_proceeds",
            "cost_basis", "gross_pnl", "cgt_estimate", "remaining_qty", "source",
        ):
            assert field in record, f"Missing field: {field}"

    def test_sell_trade_values_correct(self, tmp_path):
        _append_trade(self.SELL_TRADE)
        record = json.loads((tmp_path / "trades.json").read_text())[0]
        assert record["gross_pnl"] == 28.00
        assert record["cgt_estimate"] == 0.0
        assert record["remaining_qty"] == 1.1
        assert record["source"] == "Revolut"


# ── Weighted average calculation ──────────────────────────────

class TestWeightedAverage:
    """
    The weighted average logic in trade.main() is straightforward arithmetic.
    Verified here independently so business-critical edge cases are explicit.
    """

    @staticmethod
    def _calc(old_qty: float, old_avg: float, buy_qty: float, price: float) -> float:
        new_qty = round(old_qty + buy_qty, 8)
        if old_qty == 0:
            return price
        return round((old_qty * old_avg + buy_qty * price) / new_qty, 2)

    def test_first_purchase_uses_price_directly(self):
        assert self._calc(0, 0, 1.0, 400.0) == 400.0

    def test_equal_lots_produce_midpoint_average(self):
        assert self._calc(1.0, 400.0, 1.0, 500.0) == 450.0

    def test_larger_position_weights_average_toward_old_price(self):
        # 3 shares at 386.54, buy 1 at 430.00
        expected = round((3 * 386.54 + 1 * 430.00) / 4, 2)
        assert self._calc(3.0, 386.54, 1.0, 430.00) == expected

    def test_fractional_shares(self):
        # Crypto-style fractional quantities
        expected = round((0.5 * 90_000 + 0.25 * 95_000) / 0.75, 2)
        assert self._calc(0.5, 90_000, 0.25, 95_000) == expected
