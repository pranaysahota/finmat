"""
Tests for modules/price_fetcher.py — stock and crypto price fetching.
All HTTP calls are mocked; no real network requests are made.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.price_fetcher as pf_mod
from modules.price_fetcher import (  # noqa: E402
    MAX_RETRIES,
    get_all_prices,
    get_crypto_price,
    get_stock_price,
)


# ── Shared mock response helpers ─────────────────────────────

YAHOO_SUCCESS = {
    "chart": {
        "result": [{"meta": {"regularMarketPrice": 415.75}}]
    }
}

COINGECKO_SUCCESS = {
    "bitcoin": {"usd": 96200.50}
}


def _http_ok(json_data: dict) -> MagicMock:
    """Return a mock requests.Response that succeeds with the given JSON."""
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


# ── get_stock_price ───────────────────────────────────────────

class TestGetStockPrice:

    def test_returns_price_on_success(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(YAHOO_SUCCESS)):
            assert get_stock_price("MSFT") == 415.75

    def test_price_rounded_to_2_decimal_places(self):
        data = {"chart": {"result": [{"meta": {"regularMarketPrice": 415.7512345}}]}}
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(data)):
            assert get_stock_price("MSFT") == 415.75

    def test_returns_none_on_connection_error(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("timeout")):
            with patch("modules.price_fetcher.time.sleep"):
                assert get_stock_price("MSFT") is None

    def test_retries_correct_number_of_times(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("err")) as mock_get:
            with patch("modules.price_fetcher.time.sleep"):
                get_stock_price("MSFT")
        # total attempts = MAX_RETRIES + 1
        assert mock_get.call_count == MAX_RETRIES + 1

    def test_sleeps_between_retries(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("err")):
            with patch("modules.price_fetcher.time.sleep") as mock_sleep:
                get_stock_price("MSFT")
        assert mock_sleep.call_count == MAX_RETRIES

    def test_succeeds_on_second_attempt(self):
        responses = [Exception("timeout"), _http_ok(YAHOO_SUCCESS)]
        with patch("modules.price_fetcher.requests.get", side_effect=responses) as mock_get:
            with patch("modules.price_fetcher.time.sleep"):
                price = get_stock_price("MSFT")
        assert price == 415.75
        assert mock_get.call_count == 2

    def test_returns_none_on_malformed_response(self):
        bad = {"chart": {"result": None}}
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(bad)):
            with patch("modules.price_fetcher.time.sleep"):
                assert get_stock_price("MSFT") is None

    def test_returns_none_on_http_error(self):
        mock = MagicMock()
        mock.raise_for_status.side_effect = Exception("HTTP 429")
        with patch("modules.price_fetcher.requests.get", return_value=mock):
            with patch("modules.price_fetcher.time.sleep"):
                assert get_stock_price("MSFT") is None

    def test_correct_url_called_for_ticker(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(YAHOO_SUCCESS)) as mock_get:
            get_stock_price("NVDA")
        called_url = mock_get.call_args.args[0]
        assert "NVDA" in called_url

    def test_dot_in_ticker_replaced_with_dash_in_url(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(YAHOO_SUCCESS)) as mock_get:
            get_stock_price("BRK.B")
        called_url = mock_get.call_args.args[0]
        assert "BRK-B" in called_url
        assert "BRK.B" not in called_url

    def test_user_agent_header_sent(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(YAHOO_SUCCESS)) as mock_get:
            get_stock_price("MSFT")
        headers = mock_get.call_args.kwargs.get("headers", {})
        assert "User-Agent" in headers


# ── get_crypto_price ──────────────────────────────────────────

class TestGetCryptoPrice:

    def test_returns_price_on_success(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(COINGECKO_SUCCESS)):
            assert get_crypto_price("bitcoin") == 96200.50

    def test_price_rounded_to_2_decimal_places(self):
        data = {"bitcoin": {"usd": 96200.5678}}
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(data)):
            assert get_crypto_price("bitcoin") == 96200.57

    def test_returns_none_on_connection_error(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("err")):
            with patch("modules.price_fetcher.time.sleep"):
                assert get_crypto_price("bitcoin") is None

    def test_retries_correct_number_of_times(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("err")) as mock_get:
            with patch("modules.price_fetcher.time.sleep"):
                get_crypto_price("bitcoin")
        assert mock_get.call_count == MAX_RETRIES + 1

    def test_sleeps_between_retries(self):
        with patch("modules.price_fetcher.requests.get", side_effect=Exception("err")):
            with patch("modules.price_fetcher.time.sleep") as mock_sleep:
                get_crypto_price("bitcoin")
        assert mock_sleep.call_count == MAX_RETRIES

    def test_succeeds_on_second_attempt(self):
        responses = [Exception("timeout"), _http_ok(COINGECKO_SUCCESS)]
        with patch("modules.price_fetcher.requests.get", side_effect=responses) as mock_get:
            with patch("modules.price_fetcher.time.sleep"):
                price = get_crypto_price("bitcoin")
        assert price == 96200.50
        assert mock_get.call_count == 2

    def test_returns_none_when_coin_missing_from_response(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok({})):
            with patch("modules.price_fetcher.time.sleep"):
                assert get_crypto_price("bitcoin") is None

    def test_correct_params_sent(self):
        with patch("modules.price_fetcher.requests.get", return_value=_http_ok(COINGECKO_SUCCESS)) as mock_get:
            get_crypto_price("ethereum")
        params = mock_get.call_args.kwargs.get("params", {})
        assert params["ids"] == "ethereum"
        assert params["vs_currencies"] == "usd"


# ── get_all_prices ────────────────────────────────────────────

class TestGetAllPrices:

    @pytest.fixture(autouse=True)
    def patch_crypto_active(self, monkeypatch):
        """Existing tests assume crypto is active (all tickers fetched)."""
        monkeypatch.setattr(pf_mod, "CRYPTO_ACTIVE", True)

    PORTFOLIO = {
        "Diversified": {
            "MSFT": {"type": "stock",  "qty": 3.1, "avg_buy": 386.54,
                     "allocation_usd": 0, "bucket_pct": 0},
            "XOM":  {"type": "stock",  "qty": 0,   "avg_buy": 0.0,
                     "allocation_usd": 0, "bucket_pct": 0},
        },
        "Growth": {
            "NVDA": {"type": "stock",  "qty": 0,   "avg_buy": 0.0,
                     "allocation_usd": 0, "bucket_pct": 0},
        },
        "Crypto": {
            "bitcoin":  {"type": "crypto", "qty": 0, "avg_buy": 0.0,
                         "allocation_usd": 0, "bucket_pct": 0},
            "ethereum": {"type": "crypto", "qty": 0, "avg_buy": 0.0,
                         "allocation_usd": 0, "bucket_pct": 0},
        },
    }

    def test_returns_all_tickers(self):
        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0):
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0):
                prices = get_all_prices(self.PORTFOLIO)
        assert set(prices.keys()) == {"MSFT", "XOM", "NVDA", "bitcoin", "ethereum"}

    def test_stocks_routed_to_get_stock_price(self):
        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0) as mock_stock:
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0):
                get_all_prices(self.PORTFOLIO)
        fetched = {c.args[0] for c in mock_stock.call_args_list}
        assert fetched == {"MSFT", "XOM", "NVDA"}

    def test_crypto_routed_to_get_crypto_price(self):
        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0):
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0) as mock_crypto:
                get_all_prices(self.PORTFOLIO)
        fetched = {c.args[0] for c in mock_crypto.call_args_list}
        assert fetched == {"bitcoin", "ethereum"}

    def test_correct_prices_mapped_to_tickers(self):
        def mock_stock(ticker):
            return {"MSFT": 415.75, "XOM": 116.30, "NVDA": 138.50}[ticker]

        def mock_crypto(coin_id):
            return {"bitcoin": 96200.0, "ethereum": 2750.0}[coin_id]

        with patch("modules.price_fetcher.get_stock_price",  side_effect=mock_stock):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=mock_crypto):
                prices = get_all_prices(self.PORTFOLIO)

        assert prices["MSFT"]     == 415.75
        assert prices["XOM"]      == 116.30
        assert prices["NVDA"]     == 138.50
        assert prices["bitcoin"]  == 96200.0
        assert prices["ethereum"] == 2750.0

    def test_failed_fetch_stored_as_none(self):
        with patch("modules.price_fetcher.get_stock_price",  return_value=None):
            with patch("modules.price_fetcher.get_crypto_price", return_value=None):
                prices = get_all_prices(self.PORTFOLIO)
        assert all(v is None for v in prices.values())

    def test_zero_qty_tickers_still_fetched(self):
        """Planned positions (qty=0) must still be fetched for display."""
        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0) as mock_stock:
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0):
                get_all_prices(self.PORTFOLIO)
        fetched = {c.args[0] for c in mock_stock.call_args_list}
        assert "XOM" in fetched   # qty=0 planned position
        assert "NVDA" in fetched  # qty=0 planned position

    def test_partial_failure_does_not_prevent_other_prices(self):
        """If one ticker fails, the rest should still return prices."""
        def mock_stock(ticker):
            if ticker == "XOM":
                return None   # simulate XOM failing
            return 100.0

        with patch("modules.price_fetcher.get_stock_price",  side_effect=mock_stock):
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0):
                prices = get_all_prices(self.PORTFOLIO)

        assert prices["XOM"]  is None
        assert prices["MSFT"] == 100.0
        assert prices["NVDA"] == 100.0

    def test_crypto_tickers_not_fetched_when_inactive(self, monkeypatch):
        """When CRYPTO_ACTIVE=False the Crypto bucket is skipped entirely."""
        monkeypatch.setattr(pf_mod, "CRYPTO_ACTIVE", False)
        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0):
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0) as mock_crypto:
                prices = get_all_prices(self.PORTFOLIO)
        mock_crypto.assert_not_called()
        assert "bitcoin"  not in prices
        assert "ethereum" not in prices
