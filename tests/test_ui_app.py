"""Tests for Flask dashboard API routes."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import ui.app as app_mod  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_mod, "DASHBOARD_PASSWORD", "")
    app_mod.app.config.update(TESTING=True)
    return app_mod.app.test_client()


def test_portfolio_response_includes_qty_and_realized_pnl(client, monkeypatch):
    portfolio = {
        "Diversified": {
            "MSFT": {
                "type": "stock",
                "qty": 2.5,
                "avg_buy": 100.0,
                "allocation_usd": 0,
                "bucket_pct": 0,
            }
        }
    }
    state = {
        "total_value": 300.0,
        "total_cost": 250.0,
        "total_pnl_usd": 50.0,
        "total_pnl_pct": 20.0,
        "bucket_weights": {"Diversified": 100.0},
        "holdings": {
            "MSFT": {
                "bucket": "Diversified",
                "current_price": 120.0,
                "current_value": 300.0,
                "cost_basis": 250.0,
                "pnl_pct": 20.0,
                "pnl_usd": 50.0,
            }
        },
    }

    monkeypatch.setattr(app_mod, "load_portfolio", lambda: portfolio)
    monkeypatch.setattr(app_mod, "get_all_prices", lambda p: {"MSFT": 120.0})
    monkeypatch.setattr(app_mod, "calculate_portfolio", lambda prices, p: state)
    monkeypatch.setattr(
        app_mod,
        "get_realized_pnl_breakdown",
        lambda: {"profit": 20.00, "loss": 7.66, "pnl": 12.34},
    )

    res = client.get("/api/portfolio")
    data = res.get_json()

    assert res.status_code == 200
    assert data["realized_profit_usd"] == 20.00
    assert data["realized_loss_usd"] == 7.66
    assert data["realized_pnl_usd"] == 12.34
    assert data["holdings"][0]["qty"] == 2.5
    assert data["holdings"][0]["cost_basis"] == 250.0


def test_watchlist_response_includes_quote_and_failed_rows(client, monkeypatch):
    monkeypatch.setattr(app_mod, "get_watchlist_tickers", lambda: ["MSFT", "BAD"])

    def quote(ticker):
        if ticker == "MSFT":
            return {"current_price": 110.0, "previous_close": 100.0}
        return None

    monkeypatch.setattr(app_mod, "get_stock_quote", quote)

    res = client.get("/api/watchlist")
    data = res.get_json()

    assert res.status_code == 200
    assert data[0] == {
        "ticker": "MSFT",
        "current_price": 110.0,
        "previous_close": 100.0,
        "change_pct": 10.0,
    }
    assert data[1] == {
        "ticker": "BAD",
        "current_price": None,
        "previous_close": None,
        "change_pct": None,
    }


def test_watchlist_add_normalizes_ticker(client, monkeypatch):
    monkeypatch.setattr(app_mod, "add_watchlist_ticker", lambda ticker: ticker.strip().upper())

    res = client.post("/api/watchlist", json={"ticker": " msft "})
    data = res.get_json()

    assert res.status_code == 200
    assert data == {"success": True, "ticker": "MSFT"}


def test_watchlist_add_requires_ticker(client):
    res = client.post("/api/watchlist", json={"ticker": ""})

    assert res.status_code == 400
    assert res.get_json()["error"] == "ticker is required"


def test_watchlist_delete_returns_removed_flag(client, monkeypatch):
    monkeypatch.setattr(app_mod, "remove_watchlist_ticker", lambda ticker: ticker.upper() == "MSFT")

    res = client.delete("/api/watchlist/msft")
    data = res.get_json()

    assert res.status_code == 200
    assert data == {"success": True, "removed": True, "ticker": "MSFT"}
