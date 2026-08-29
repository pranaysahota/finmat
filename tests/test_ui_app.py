"""Tests for the Flask API exposed by ui.app."""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import ui.app as app_module


def test_portfolio_summary_returns_only_compact_state(monkeypatch):
    state = {
        "total_value": 12345.67,
        "total_cost": 10000.00,
        "total_pnl_usd": 2345.67,
        "total_pnl_pct": 23.46,
        "bucket_weights": {"Diversified": 60.5, "Growth": 39.5},
        "bucket_targets": {"Diversified": 60, "Growth": 25, "Crypto": 15},
        "holdings": {"MSFT": {"current_value": 12345.67}},
    }
    monkeypatch.setattr(app_module, "load_portfolio", lambda: {"Diversified": {}})
    monkeypatch.setattr(app_module, "get_all_prices", lambda portfolio: {})
    monkeypatch.setattr(app_module, "calculate_portfolio", lambda prices, portfolio: state)

    response = app_module.app.test_client().get("/api/portfolio/summary")

    assert response.status_code == 200
    assert response.get_json() == {
        "total_value": 12345.67,
        "total_cost": 10000.00,
        "total_pnl_usd": 2345.67,
        "total_pnl_pct": 23.46,
        "bucket_weights": {
            "Diversified": 60.5,
            "Growth": 39.5,
            "Crypto": 0.0,
        },
    }
