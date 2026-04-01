"""
Tests for modules/history.py — save, load, query, and performance summary functions.
HISTORY_FILE and DATA_DIR are monkeypatched to temp paths for full isolation.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.history as history_mod  # noqa: E402
from modules.history import (  # noqa: E402
    get_last_snapshot,
    get_performance_summary,
    get_snapshot_by_date,
    load_history,
    save_snapshot,
)


# ── Shared test data ──────────────────────────────────────────

MOCK_STATE = {
    "total_value":    8124.50,
    "total_cost":     8000.00,
    "total_pnl_usd":  124.50,
    "total_pnl_pct":  1.56,
    "crypto_weight":  15.2,
    "bucket_values":  {"Diversified": 4900.00, "Growth": 2040.00, "Crypto": 1184.50},
    "holdings": {
        "MSFT":    {"current_value": 1300.00, "pnl_pct": 8.3,  "pnl_usd": 100.00},
        "NVDA":    {"current_value":  950.00, "pnl_pct": 5.5,  "pnl_usd":  50.00},
        "bitcoin": {"current_value":  810.00, "pnl_pct": 3.85, "pnl_usd":  30.00},
    },
}

# Two pre-built snapshots 9 days apart (no 7-day snapshot between them by default)
SNAPSHOT_A = {
    "date":          "2026-01-01",
    "timestamp":     "2026-01-01T09:00:00",
    "total_value":   10000.00,
    "total_cost":    9500.00,
    "total_pnl_usd": 500.00,
    "total_pnl_pct": 5.26,
    "crypto_weight": 12.0,
    "bucket_values": {"Diversified": 6000.00, "Growth": 2500.00, "Crypto": 1500.00},
    "holdings": {
        "MSFT":    {"current_value": 1300.00, "pnl_pct": 5.0, "pnl_usd": 65.00},
        "bitcoin": {"current_value": 1000.00, "pnl_pct": 3.0, "pnl_usd": 29.00},
    },
}

SNAPSHOT_B = {
    "date":          "2026-01-10",
    "timestamp":     "2026-01-10T09:00:00",
    "total_value":   11000.00,
    "total_cost":    9500.00,
    "total_pnl_usd": 1500.00,
    "total_pnl_pct": 15.79,
    "crypto_weight": 13.0,
    "bucket_values": {"Diversified": 6600.00, "Growth": 2750.00, "Crypto": 1650.00},
    "holdings": {
        "MSFT":    {"current_value": 1500.00, "pnl_pct": 8.0, "pnl_usd": 111.00},
        "bitcoin": {"current_value": 1100.00, "pnl_pct": 1.5, "pnl_usd":  16.00},
    },
}


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    """Redirect HISTORY_FILE and DATA_DIR to tmp_path for every test."""
    history_file = tmp_path / "portfolio_history.json"
    monkeypatch.setattr(history_mod, "HISTORY_FILE", history_file)
    monkeypatch.setattr(history_mod, "DATA_DIR", tmp_path)


# ── load_history ──────────────────────────────────────────────

class TestLoadHistory:

    def test_returns_empty_list_when_file_missing(self):
        assert load_history() == []

    def test_returns_snapshots_in_order(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        result = load_history()
        assert len(result) == 2
        assert result[0]["date"] == "2026-01-01"
        assert result[1]["date"] == "2026-01-10"

    def test_returns_empty_list_on_malformed_json(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text("not valid json{{")
        assert load_history() == []


# ── save_snapshot ─────────────────────────────────────────────

class TestSaveSnapshot:

    def test_creates_history_file(self, tmp_path):
        save_snapshot(MOCK_STATE)
        assert (tmp_path / "portfolio_history.json").exists()

    def test_snapshot_contains_required_fields(self, tmp_path):
        save_snapshot(MOCK_STATE)
        data = json.loads((tmp_path / "portfolio_history.json").read_text())
        snap = data[0]
        for key in ("date", "timestamp", "total_value", "total_cost",
                    "total_pnl_usd", "total_pnl_pct", "crypto_weight",
                    "bucket_values", "holdings"):
            assert key in snap, f"Missing key: {key}"

    def test_total_value_matches_portfolio_state(self, tmp_path):
        save_snapshot(MOCK_STATE)
        data = json.loads((tmp_path / "portfolio_history.json").read_text())
        assert data[0]["total_value"] == MOCK_STATE["total_value"]

    def test_holdings_compressed_to_three_fields(self, tmp_path):
        """Only current_value, pnl_pct, pnl_usd are stored — not the full asset dict."""
        save_snapshot(MOCK_STATE)
        data = json.loads((tmp_path / "portfolio_history.json").read_text())
        for ticker_data in data[0]["holdings"].values():
            assert set(ticker_data.keys()) == {"current_value", "pnl_pct", "pnl_usd"}

    def test_duplicate_date_skipped(self, tmp_path, capsys):
        """Calling save_snapshot twice on the same day adds only one entry."""
        save_snapshot(MOCK_STATE)
        save_snapshot(MOCK_STATE)
        data = json.loads((tmp_path / "portfolio_history.json").read_text())
        assert len(data) == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out

    def test_creates_data_dir_if_missing(self, tmp_path, monkeypatch):
        new_dir = tmp_path / "newdata"   # single level — mkdir(exist_ok=True) can create this
        new_file = new_dir / "portfolio_history.json"
        monkeypatch.setattr(history_mod, "DATA_DIR", new_dir)
        monkeypatch.setattr(history_mod, "HISTORY_FILE", new_file)
        save_snapshot(MOCK_STATE)   # must not raise even though dir didn't exist
        assert new_file.exists()

    def test_multiple_distinct_dates_all_saved(self, tmp_path):
        """Simulate two different days — both snapshots should persist."""
        # First save (today via save_snapshot's datetime.now())
        save_snapshot(MOCK_STATE)

        # Manually inject a second snapshot with a different date
        data = json.loads((tmp_path / "portfolio_history.json").read_text())
        data.append({**data[0], "date": "2025-01-01", "timestamp": "2025-01-01T09:00:00"})
        (tmp_path / "portfolio_history.json").write_text(json.dumps(data))

        assert len(load_history()) == 2


# ── get_snapshot_by_date ──────────────────────────────────────

class TestGetSnapshotByDate:

    def test_returns_correct_snapshot(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        result = get_snapshot_by_date("2026-01-01")
        assert result is not None
        assert result["total_value"] == 10000.00

    def test_returns_none_for_date_not_in_history(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        assert get_snapshot_by_date("2025-06-15") is None

    def test_returns_none_on_empty_history(self):
        assert get_snapshot_by_date("2026-01-01") is None

    def test_retrieves_second_snapshot_correctly(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        result = get_snapshot_by_date("2026-01-10")
        assert result["total_value"] == 11000.00


# ── get_last_snapshot ─────────────────────────────────────────

class TestGetLastSnapshot:

    def test_returns_none_when_history_empty(self):
        assert get_last_snapshot() is None

    def test_returns_last_snapshot_from_multiple(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        result = get_last_snapshot()
        assert result["date"] == "2026-01-10"

    def test_returns_only_entry_when_one_snapshot(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A])
        )
        result = get_last_snapshot()
        assert result["date"] == "2026-01-01"


# ── get_performance_summary ───────────────────────────────────

class TestGetPerformanceSummary:

    def test_returns_empty_dict_with_no_history(self):
        assert get_performance_summary() == {}

    def test_returns_empty_dict_with_one_snapshot(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A])
        )
        assert get_performance_summary() == {}

    def test_since_inception_usd_correct(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        # Uses latest total_pnl_usd — cost-adjusted, unaffected by new capital additions
        assert summary["since_inception_usd"] == SNAPSHOT_B["total_pnl_usd"]

    def test_since_inception_pct_correct(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        # Uses latest total_pnl_pct — cost-adjusted, unaffected by new capital additions
        assert summary["since_inception_pct"] == SNAPSHOT_B["total_pnl_pct"]

    def test_last_7_days_pct_none_when_no_7_day_snapshot(self, tmp_path):
        """Snapshots A→B are 9 days apart — no exact 7-days-ago match."""
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        assert summary["last_7_days_pct"] is None

    def test_last_7_days_pct_computed_when_snapshot_exists(self, tmp_path):
        """Insert a snapshot exactly 7 days before SNAPSHOT_B (2026-01-10)."""
        seven_days_snap = {
            **SNAPSHOT_A,
            "date":          "2026-01-03",
            "timestamp":     "2026-01-03T09:00:00",
            "total_value":   10500.00,
        }
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, seven_days_snap, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        # pnl_change = SNAPSHOT_B.total_pnl_usd - seven_days_snap.total_pnl_usd
        # seven_days_snap inherits total_pnl_usd=500.00, total_cost=9500.00 from SNAPSHOT_A
        pnl_change = SNAPSHOT_B["total_pnl_usd"] - seven_days_snap["total_pnl_usd"]
        expected   = round(pnl_change / seven_days_snap["total_cost"] * 100, 2)
        assert summary["last_7_days_pct"] == expected

    def test_best_performer_is_highest_pnl_pct(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        # SNAPSHOT_B: MSFT pnl_pct=8.0, bitcoin pnl_pct=1.5
        assert summary["best_performer"]["ticker"] == "MSFT"
        assert summary["best_performer"]["pnl_pct"] == 8.0

    def test_worst_performer_is_lowest_pnl_pct(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        assert summary["worst_performer"]["ticker"] == "bitcoin"
        assert summary["worst_performer"]["pnl_pct"] == 1.5

    def test_summary_metadata_fields(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        assert summary["total_snapshots"] == 2
        assert summary["first_date"] == "2026-01-01"
        assert summary["latest_date"] == "2026-01-10"

    def test_all_expected_keys_present(self, tmp_path):
        (tmp_path / "portfolio_history.json").write_text(
            json.dumps([SNAPSHOT_A, SNAPSHOT_B])
        )
        summary = get_performance_summary()
        expected_keys = {
            "since_inception_pct", "since_inception_usd",
            "last_7_days_pct", "best_performer", "worst_performer",
            "total_snapshots", "first_date", "latest_date",
        }
        assert expected_keys == summary.keys()
