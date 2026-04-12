"""
Schema validation tests for the PORTFOLIO dict.

Loads portfolio/local.py if present, otherwise falls back to
portfolio/local.example.py so tests always run in clean CI environments.
These tests validate structure and types — not live prices or business logic.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# ── Helpers ──────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent

REQUIRED_BUCKETS    = {"Diversified", "Growth", "Crypto"}
REQUIRED_ASSET_KEYS = {"type", "qty", "avg_buy", "allocation_usd", "bucket_pct"}
VALID_TYPES         = {"stock", "crypto"}
BUCKET_TYPE_MAP     = {"Diversified": "stock", "Growth": "stock", "Crypto": "crypto"}


def _load_module_from_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_portfolio() -> dict:
    """Load PORTFOLIO — prefer local.py, fall back to example in CI."""
    local_path   = ROOT / "portfolio" / "local.py"
    example_path = ROOT / "portfolio" / "local.example.py"

    if local_path.exists():
        return _load_module_from_file("portfolio_local", local_path).PORTFOLIO
    return _load_module_from_file("portfolio_example", example_path).PORTFOLIO


def _is_placeholder(portfolio: dict) -> bool:
    """Return True if any asset has qty == 0 or bucket_pct == 0 (portfolio not fully configured).

    Constraint tests are skipped until every planned position has been filled,
    because bucket_pct sums and avg_buy checks only make sense on a complete
    portfolio.
    """
    return any(
        asset["qty"] == 0 or asset["bucket_pct"] == 0
        for bucket in portfolio.values()
        for asset in bucket.values()
    )


# ── Fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="module")
def portfolio() -> dict:
    return _load_portfolio()


@pytest.fixture(scope="module")
def all_assets(portfolio) -> list[tuple[str, str, dict]]:
    """Flat list of (bucket_name, ticker, asset_dict)."""
    return [
        (bucket, ticker, asset)
        for bucket, holdings in portfolio.items()
        for ticker, asset in holdings.items()
    ]


@pytest.fixture(scope="module")
def is_placeholder(portfolio) -> bool:
    return _is_placeholder(portfolio)


# ── Structure tests ───────────────────────────────────────────

class TestPortfolioStructure:

    def test_portfolio_is_a_dict(self, portfolio):
        assert isinstance(portfolio, dict), "PORTFOLIO must be a dict"

    def test_required_buckets_present(self, portfolio):
        missing = REQUIRED_BUCKETS - portfolio.keys()
        assert not missing, f"Missing buckets: {missing}"

    def test_no_unexpected_buckets(self, portfolio):
        extra = portfolio.keys() - REQUIRED_BUCKETS
        assert not extra, f"Unexpected buckets: {extra}"

    def test_each_bucket_is_a_dict(self, portfolio):
        for bucket, holdings in portfolio.items():
            assert isinstance(holdings, dict), f"Bucket '{bucket}' must be a dict"

    def test_each_bucket_has_at_least_one_asset(self, portfolio):
        for bucket, holdings in portfolio.items():
            assert len(holdings) > 0, f"Bucket '{bucket}' is empty"

    def test_no_duplicate_tickers_across_buckets(self, portfolio):
        all_tickers = [
            ticker
            for holdings in portfolio.values()
            for ticker in holdings
        ]
        seen, dupes = set(), set()
        for t in all_tickers:
            (dupes if t in seen else seen).add(t)
        assert not dupes, f"Duplicate tickers found across buckets: {dupes}"


# ── Per-asset key tests ───────────────────────────────────────

class TestAssetKeys:

    def test_all_required_keys_present(self, all_assets):
        for bucket, ticker, asset in all_assets:
            missing = REQUIRED_ASSET_KEYS - asset.keys()
            assert not missing, (
                f"{bucket}/{ticker} is missing keys: {missing}"
            )

    def test_no_unexpected_keys(self, all_assets):
        for bucket, ticker, asset in all_assets:
            extra = asset.keys() - REQUIRED_ASSET_KEYS
            assert not extra, (
                f"{bucket}/{ticker} has unexpected keys: {extra}"
            )


# ── Type field tests ──────────────────────────────────────────

class TestAssetTypes:

    def test_type_field_is_valid_string(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert asset["type"] in VALID_TYPES, (
                f"{bucket}/{ticker}: type='{asset['type']}' "
                f"must be one of {VALID_TYPES}"
            )

    def test_diversified_bucket_assets_are_stock_type(self, portfolio):
        for ticker, asset in portfolio["Diversified"].items():
            assert asset["type"] == "stock", (
                f"Diversified/{ticker}: type must be 'stock', got '{asset['type']}'"
            )

    def test_growth_bucket_assets_are_stock_type(self, portfolio):
        for ticker, asset in portfolio["Growth"].items():
            assert asset["type"] == "stock", (
                f"Growth/{ticker}: type must be 'stock', got '{asset['type']}'"
            )


# ── Numeric field type tests ──────────────────────────────────

class TestAssetFieldTypes:

    def test_qty_is_numeric(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert isinstance(asset["qty"], (int, float)), (
                f"{bucket}/{ticker}: qty must be int or float"
            )

    def test_avg_buy_is_numeric(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert isinstance(asset["avg_buy"], (int, float)), (
                f"{bucket}/{ticker}: avg_buy must be int or float"
            )

    def test_allocation_usd_is_numeric(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert isinstance(asset["allocation_usd"], (int, float)), (
                f"{bucket}/{ticker}: allocation_usd must be int or float"
            )

    def test_bucket_pct_is_numeric(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert isinstance(asset["bucket_pct"], (int, float)), (
                f"{bucket}/{ticker}: bucket_pct must be numeric"
            )

    def test_all_numeric_fields_are_non_negative(self, all_assets):
        fields = ("qty", "avg_buy", "allocation_usd", "bucket_pct")
        for bucket, ticker, asset in all_assets:
            for field in fields:
                assert asset[field] >= 0, (
                    f"{bucket}/{ticker}: {field}={asset[field]} must be >= 0"
                )

    def test_bucket_pct_within_0_to_100(self, all_assets):
        for bucket, ticker, asset in all_assets:
            assert 0 <= asset["bucket_pct"] <= 100, (
                f"{bucket}/{ticker}: bucket_pct={asset['bucket_pct']} "
                f"must be between 0 and 100"
            )


# ── Numeric constraint tests (skipped for placeholder zeros) ──

class TestAssetValueConstraints:

    def test_bucket_pcts_sum_to_100_per_bucket(self, portfolio, is_placeholder):
        if is_placeholder:
            pytest.skip("Skipping sum check — placeholder file with zero values")
        for bucket, holdings in portfolio.items():
            total = sum(asset["bucket_pct"] for asset in holdings.values())
            assert total == 100, (
                f"Bucket '{bucket}': bucket_pct values sum to {total}, expected 100"
            )

    def test_qty_positive_for_real_holdings(self, all_assets, is_placeholder):
        if is_placeholder:
            pytest.skip("Skipping qty > 0 check — placeholder file")
        for bucket, ticker, asset in all_assets:
            assert asset["qty"] > 0, (
                f"{bucket}/{ticker}: qty must be > 0 for real holdings"
            )

    def test_avg_buy_positive_for_real_holdings(self, all_assets, is_placeholder):
        if is_placeholder:
            pytest.skip("Skipping avg_buy > 0 check — placeholder file")
        for bucket, ticker, asset in all_assets:
            assert asset["avg_buy"] > 0, (
                f"{bucket}/{ticker}: avg_buy must be > 0 for real holdings"
            )

    def test_allocation_usd_positive_for_real_holdings(self, all_assets, is_placeholder):
        if is_placeholder:
            pytest.skip("Skipping allocation_usd > 0 check — placeholder file")
        for bucket, ticker, asset in all_assets:
            assert asset["allocation_usd"] > 0, (
                f"{bucket}/{ticker}: allocation_usd must be > 0 for real holdings"
            )


# ── Config schema tests ───────────────────────────────────────

class TestConfigSchema:

    def test_rules_has_required_keys(self):
        sys.path.insert(0, str(ROOT))
        # Import config constants directly without triggering SystemExit
        import importlib
        spec = importlib.util.spec_from_file_location("config_mod", ROOT / "config.py")
        # We can't fully import config.py as it calls load_dotenv and imports PORTFOLIO,
        # so we validate the RULES and BUCKET_TARGETS shapes via the portfolio fixture instead.
        # This test intentionally validates using known expected keys.
        expected_rule_keys = {"stop_loss_pct", "take_profit_pct", "crypto_max_weight", "bucket_drift_pct", "benchmark"}
        from config import RULES
        missing = expected_rule_keys - RULES.keys()
        assert not missing, f"RULES is missing keys: {missing}"

    def test_bucket_targets_has_required_keys(self):
        from config import BUCKET_TARGETS
        assert set(BUCKET_TARGETS.keys()) == {"Diversified", "Growth", "Crypto"}

    def test_bucket_targets_sum_to_100(self):
        from config import BUCKET_TARGETS
        total = sum(BUCKET_TARGETS.values())
        assert total == 100, f"BUCKET_TARGETS sum to {total}, expected 100"

    def test_stop_loss_is_negative(self):
        from config import RULES
        assert RULES["stop_loss_pct"] < 0, "stop_loss_pct must be negative"

    def test_take_profit_is_positive(self):
        from config import RULES
        assert RULES["take_profit_pct"] > 0, "take_profit_pct must be positive"

    def test_paths_has_required_keys(self):
        from config import PATHS
        assert "DATA_DIR" in PATHS
        assert "HISTORY_FILE" in PATHS
        # TRADES_FILE removed — trades now stored in SQLite

    def test_paths_are_pathlib_paths(self):
        from config import PATHS
        for key, value in PATHS.items():
            assert isinstance(value, Path), f"PATHS['{key}'] must be a pathlib.Path"
