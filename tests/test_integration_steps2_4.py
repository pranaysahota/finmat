"""
Integration tests for Steps 2–4.

Verifies that config/portfolio (Step 2), trade.py (Step 2b), history.py (Step 3),
and price_fetcher.py (Step 4) work correctly as a pipeline:

  portfolio/local.py  →  get_all_prices()  →  save_snapshot()  →  load_history()

All HTTP calls are mocked; file I/O for history is redirected to tmp_path.
trade.py file writes use a temporary copy of portfolio/local.py.
"""

import pytest

pytestmark = pytest.mark.integration

import importlib.util
import json
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
    "MSFT":     415.75,
    "AAPL":     232.10,
    "JPM":      247.80,
    "JNJ":      156.20,
    "ASML":     685.40,
    "BRK.B":    478.90,
    "XOM":      116.30,
    "GOOG":     178.20,
    "NVDA":     138.50,
    "bitcoin":  96200.0,
    "ethereum":  2750.0,
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
        """These tests validate the full portfolio structure including Crypto."""
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


# ── Step 4 + 3: Price Fetcher → History ──────────────────────

class TestPriceFetcherToHistory:
    """Prices from get_all_prices feed into save_snapshot correctly."""

    @pytest.fixture(autouse=True)
    def patch_history_paths(self, tmp_path, monkeypatch):
        import modules.history as history_mod
        monkeypatch.setattr(history_mod, "HISTORY_FILE", tmp_path / "portfolio_history.json")
        monkeypatch.setattr(history_mod, "DATA_DIR", tmp_path)

    def _build_portfolio_state(self, portfolio: dict, prices: dict) -> dict:
        """Minimal portfolio_state built from holdings × prices (no portfolio.py yet)."""
        holdings = {}
        for bucket, assets in portfolio.items():
            for ticker, asset in assets.items():
                price = prices.get(ticker)
                if price is None:
                    continue
                cost_basis    = round(asset["qty"] * asset["avg_buy"], 2)
                current_value = round(asset["qty"] * price, 2)
                pnl_usd       = round(current_value - cost_basis, 2)
                pnl_pct       = round((pnl_usd / cost_basis) * 100, 2) if cost_basis else 0.0
                holdings[ticker] = {
                    "current_value": current_value,
                    "pnl_pct":       pnl_pct,
                    "pnl_usd":       pnl_usd,
                }

        total_value = round(sum(h["current_value"] for h in holdings.values()), 2)
        return {
            "total_value":    total_value,
            "total_cost":     0.0,
            "total_pnl_usd":  0.0,
            "total_pnl_pct":  0.0,
            "crypto_weight":  0.0,
            "bucket_values":  {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "holdings":       holdings,
        }

    def test_snapshot_saved_after_price_fetch(self, tmp_path):
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot, load_history

        portfolio = _load_portfolio_from_file(ROOT / "portfolio" / "local.py")

        with patch("modules.price_fetcher.get_stock_price",  side_effect=lambda t: MOCK_PRICES.get(t)):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=lambda c: MOCK_PRICES.get(c)):
                prices = get_all_prices(portfolio)

        state = self._build_portfolio_state(portfolio, prices)
        save_snapshot(state)

        history = load_history()
        assert len(history) == 1
        assert "date" in history[0]
        assert "total_value" in history[0]

    def test_snapshot_holdings_contain_only_tickers_with_prices(self, tmp_path):
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot, load_history

        portfolio = _load_portfolio_from_file(ROOT / "portfolio" / "local.py")

        # Make one ticker fail
        def mock_stock(ticker):
            if ticker == "AAPL":
                return None
            return MOCK_PRICES.get(ticker, 100.0)

        with patch("modules.price_fetcher.get_stock_price",  side_effect=mock_stock):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=lambda c: MOCK_PRICES.get(c)):
                prices = get_all_prices(portfolio)

        state = self._build_portfolio_state(portfolio, prices)
        save_snapshot(state)

        snap = load_history()[0]
        # AAPL had no price → excluded from holdings (qty=0 anyway so cost_basis=0)
        assert "AAPL" not in snap["holdings"]

    def test_snapshot_holdings_match_expected_schema(self, tmp_path):
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot, load_history

        portfolio = _load_portfolio_from_file(ROOT / "portfolio" / "local.py")

        with patch("modules.price_fetcher.get_stock_price",  side_effect=lambda t: MOCK_PRICES.get(t)):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=lambda c: MOCK_PRICES.get(c)):
                prices = get_all_prices(portfolio)

        state = self._build_portfolio_state(portfolio, prices)
        save_snapshot(state)

        snap = load_history()[0]
        for ticker, data in snap["holdings"].items():
            assert set(data.keys()) == {"current_value", "pnl_pct", "pnl_usd"}, \
                f"{ticker} holding has unexpected keys: {data.keys()}"


# ── Full pipeline: Steps 2–4 ──────────────────────────────────

class TestFullPipeline:
    """
    End-to-end: load real PORTFOLIO from config, mock prices,
    save a history snapshot, and verify round-trip integrity.
    """

    @pytest.fixture(autouse=True)
    def patch_history_paths(self, tmp_path, monkeypatch):
        import modules.history as history_mod
        monkeypatch.setattr(history_mod, "HISTORY_FILE", tmp_path / "portfolio_history.json")
        monkeypatch.setattr(history_mod, "DATA_DIR", tmp_path)

    def test_pipeline_snapshot_has_all_required_top_level_fields(self, tmp_path):
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot, load_history

        with patch("modules.price_fetcher.get_stock_price",  side_effect=lambda t: MOCK_PRICES.get(t)):
            with patch("modules.price_fetcher.get_crypto_price", side_effect=lambda c: MOCK_PRICES.get(c)):
                prices = get_all_prices(PORTFOLIO)

        # Build minimal portfolio_state from prices
        holdings_snap = {}
        for bucket, assets in PORTFOLIO.items():
            for ticker, asset in assets.items():
                price = prices.get(ticker)
                if price is None:
                    continue
                holdings_snap[ticker] = {
                    "current_value": round(asset["qty"] * price, 2),
                    "pnl_pct":       0.0,
                    "pnl_usd":       0.0,
                }

        state = {
            "total_value":    round(sum(h["current_value"] for h in holdings_snap.values()), 2),
            "total_cost":     0.0,
            "total_pnl_usd":  0.0,
            "total_pnl_pct":  0.0,
            "crypto_weight":  0.0,
            "bucket_values":  {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "holdings":       holdings_snap,
        }

        save_snapshot(state)
        snap = load_history()[0]

        for field in ("date", "timestamp", "total_value", "total_cost",
                      "total_pnl_usd", "total_pnl_pct", "crypto_weight",
                      "bucket_values", "holdings"):
            assert field in snap, f"Snapshot missing field: {field}"

    def test_msft_value_correct_given_real_qty(self, tmp_path):
        """MSFT is the only position with qty > 0 — its snapshot value is verifiable."""
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot, load_history

        if "MSFT" not in PORTFOLIO.get("Diversified", {}):
            pytest.skip("MSFT not in portfolio (CI using example file)")

        msft_price = 415.75
        msft_qty   = PORTFOLIO["Diversified"]["MSFT"]["qty"]   # 3.1

        with patch("modules.price_fetcher.get_stock_price",  return_value=msft_price):
            with patch("modules.price_fetcher.get_crypto_price", return_value=96200.0):
                prices = get_all_prices(PORTFOLIO)

        holdings_snap = {}
        for bucket, assets in PORTFOLIO.items():
            for ticker, asset in assets.items():
                price = prices.get(ticker)
                if price is not None:
                    holdings_snap[ticker] = {
                        "current_value": round(asset["qty"] * price, 2),
                        "pnl_pct":       0.0,
                        "pnl_usd":       0.0,
                    }

        state = {
            "total_value":   round(sum(h["current_value"] for h in holdings_snap.values()), 2),
            "total_cost":    0.0, "total_pnl_usd": 0.0, "total_pnl_pct": 0.0,
            "crypto_weight": 0.0,
            "bucket_values": {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "holdings":      holdings_snap,
        }

        save_snapshot(state)
        snap = load_history()[0]

        expected_msft_value = round(msft_qty * msft_price, 2)
        assert snap["holdings"]["MSFT"]["current_value"] == expected_msft_value

    def test_snapshot_is_reloadable_and_parseable(self, tmp_path):
        """History file written by the pipeline can be read back as valid JSON."""
        from config import PORTFOLIO
        from modules.price_fetcher import get_all_prices
        from modules.history import save_snapshot

        with patch("modules.price_fetcher.get_stock_price",  return_value=100.0):
            with patch("modules.price_fetcher.get_crypto_price", return_value=1000.0):
                prices = get_all_prices(PORTFOLIO)

        holdings_snap = {
            ticker: {"current_value": round(asset["qty"] * prices[ticker], 2),
                     "pnl_pct": 0.0, "pnl_usd": 0.0}
            for bucket, assets in PORTFOLIO.items()
            for ticker, asset in assets.items()
            if prices.get(ticker) is not None
        }

        state = {
            "total_value":   0.0, "total_cost": 0.0,
            "total_pnl_usd": 0.0, "total_pnl_pct": 0.0, "crypto_weight": 0.0,
            "bucket_values": {"Diversified": 0.0, "Growth": 0.0, "Crypto": 0.0},
            "holdings":      holdings_snap,
        }

        save_snapshot(state)

        history_file = tmp_path / "portfolio_history.json"
        raw = json.loads(history_file.read_text())
        assert isinstance(raw, list)
        assert len(raw) == 1
