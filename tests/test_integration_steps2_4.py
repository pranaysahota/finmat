"""
Integration tests for Steps 2 and 4.

Verifies that config/portfolio (Step 2), trade.py (Step 2b), and
price_fetcher.py (Step 4) work correctly as a pipeline:

  portfolio/local.py  →  get_all_prices()

All HTTP calls are mocked; trade.py file writes use a temporary copy of
portfolio/local.py.
"""

import pytest

pytestmark = pytest.mark.integration

import importlib.util
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ── Shared mock data ──────────────────────────────────────────

# Prices that cover every ticker in the real PORTFOLIO
MOCK_PRICES = {
    "MSFT":  415.75,
    "AAPL":  232.10,
    "JPM":   247.80,
    "GOOGL": 178.20,
}

# Minimal portfolio source for file-based tests (mirrors local.py structure)
MINIMAL_PORTFOLIO_SOURCE = textwrap.dedent("""\
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
    }
""")


def _load_portfolio_from_file(path: Path) -> dict:
    """Load PORTFOLIO dict from an arbitrary .py file path."""
    spec = importlib.util.spec_from_file_location("_portfolio_tmp", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PORTFOLIO


# ── Step 2 + 4: Config → Price Fetcher ───────────────────────

class TestConfigToPriceFetcher:
    """The real PORTFOLIO from config is fully covered by get_all_prices."""

    @pytest.fixture(autouse=True)
    def patch_crypto_active(self, monkeypatch):
        """Force CRYPTO_ACTIVE=True so get_all_prices processes the Crypto bucket.

        These tests validate full portfolio coverage — all buckets including Crypto
        must be iterated. API calls are mocked so no real network requests are made.
        """
        import modules.price_fetcher as pf_mod
        monkeypatch.setattr(pf_mod, "CRYPTO_ACTIVE", True)

    def test_every_ticker_appears_in_prices(self):
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices

        with patch("modules.price_fetcher.get_stock_price",  side_effect=lambda t: MOCK_PRICES.get(t)):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=lambda c: MOCK_PRICES.get(c)):
                prices = get_all_prices(PORTFOLIO)

        for bucket, holdings in PORTFOLIO.items():
            for ticker in holdings:
                assert ticker in prices, f"{ticker} from {bucket} bucket missing in prices"

    def test_prices_dict_has_no_extra_keys(self):
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices

        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0):
            with patch("modules.price_fetcher.get_crypto_price", return_value=100.0):
                prices = get_all_prices(PORTFOLIO)

        expected = {t for holdings in PORTFOLIO.values() for t in holdings}
        assert set(prices.keys()) == expected

    def test_stock_and_crypto_types_routed_correctly(self):
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices

        expected_stocks  = {t for holdings in PORTFOLIO.values()
                            for t, a in holdings.items() if a["type"] == "stock"}
        expected_cryptos = {t for holdings in PORTFOLIO.values()
                            for t, a in holdings.items() if a["type"] == "crypto"}

        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0) as ms:
            with patch("modules.price_fetcher.get_crypto_price", return_value=100.0) as mc:
                get_all_prices(PORTFOLIO)

        assert {c.args[0] for c in ms.call_args_list} == expected_stocks
        assert {c.args[0] for c in mc.call_args_list} == expected_cryptos

    def test_config_bucket_structure_matches_price_fetcher_expectations(self):
        """Every asset in PORTFOLIO has a 'type' field get_all_prices can read."""
        from config import PORTFOLIO

        for bucket, holdings in PORTFOLIO.items():
            for ticker, asset in holdings.items():
                assert "type" in asset, f"{bucket}/{ticker} missing 'type'"
                assert asset["type"] in ("stock", "crypto"), \
                    f"{bucket}/{ticker} has unknown type '{asset['type']}'"


# ── Step 2b + 4: Trade → Price Fetcher ───────────────────────

class TestTradeThenPriceFetch:
    """After trade.py updates portfolio/local.py, the new ticker is included in prices."""

    @pytest.fixture
    def portfolio_file(self, tmp_path):
        f = tmp_path / "local.py"
        f.write_text(MINIMAL_PORTFOLIO_SOURCE)
        return f

    def test_newly_added_ticker_included_in_prices(self, portfolio_file, monkeypatch):
        import trade
        from modules.price_fetcher import get_all_prices

        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        trade._add_new_ticker("AAPL", "Diversified", "stock", 4.17, 230.00)

        updated = _load_portfolio_from_file(portfolio_file)

        with patch("modules.price_fetcher.get_stock_price",  return_value=232.10):
            with patch("modules.price_fetcher.get_crypto_price", return_value=96200.0):
                prices = get_all_prices(updated)

        assert "AAPL" in prices
        assert prices["AAPL"] == 232.10

    def test_updated_qty_does_not_affect_price_fetch(self, portfolio_file, monkeypatch):
        """Changing qty via trade.py has no effect on what prices are fetched."""
        import trade
        from modules.price_fetcher import get_all_prices

        monkeypatch.setattr(trade, "PORTFOLIO_FILE", portfolio_file)
        trade._update_existing_ticker("MSFT", 5.6, 400.00)

        updated = _load_portfolio_from_file(portfolio_file)

        with patch("modules.price_fetcher.get_stock_price",  return_value=415.75) as mock_stock:
            with patch("modules.price_fetcher.get_crypto_price", return_value=96200.0):
                prices = get_all_prices(updated)

        # MSFT still fetched despite qty change
        fetched = {c.args[0] for c in mock_stock.call_args_list}
        assert "MSFT" in fetched
        assert prices["MSFT"] == 415.75
