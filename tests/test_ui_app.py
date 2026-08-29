"""Tests for Flask dashboard API routes."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import ui.app as app_mod  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_mod, "DASHBOARD_PASSWORD", "")
    app_mod.app.config.update(TESTING=True)
    return app_mod.app.test_client()


def test_portfolio_summary_returns_only_compact_state(client, monkeypatch):
    state = {
        "total_value": 12345.67,
        "invested_value": 12000.00,
        "cash_balance": 345.67,
        "total_cost": 10000.00,
        "total_pnl_usd": 2345.67,
        "total_pnl_pct": 23.46,
        "bucket_weights": {"Diversified": 60.5, "Growth": 39.5},
        "bucket_targets": {"Diversified": 60, "Growth": 25, "Crypto": 15},
        "holdings": {"MSFT": {"current_value": 12345.67}},
    }
    monkeypatch.setattr(app_mod, "load_portfolio", lambda: {"Diversified": {}})
    monkeypatch.setattr(app_mod, "get_all_prices", lambda portfolio: {})
    monkeypatch.setattr(
        app_mod, "calculate_portfolio",
        lambda prices, portfolio, cash_balance=0.0: state,
    )
    monkeypatch.setattr(app_mod, "get_cash_balance", lambda: 345.67)

    response = client.get("/api/portfolio/summary")

    assert response.status_code == 200
    assert response.get_json() == {
        "total_value": 12345.67,
        "invested_value": 12000.00,
        "cash_balance": 345.67,
        "total_cost": 10000.00,
        "total_pnl_usd": 2345.67,
        "total_pnl_pct": 23.46,
        "bucket_weights": {
            "Diversified": 60.5,
            "Growth": 39.5,
            "Crypto": 0.0,
        },
    }


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
        "total_value": 350.0,
        "invested_value": 300.0,
        "cash_balance": 50.0,
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
    monkeypatch.setattr(
        app_mod, "calculate_portfolio",
        lambda prices, p, cash_balance=0.0: state,
    )
    monkeypatch.setattr(app_mod, "get_cash_balance", lambda: 50.0)
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
    assert data["invested_value"] == 300.0
    assert data["cash_balance"] == 50.0
    assert data["total_value"] == 350.0
    assert data["holdings"][0]["qty"] == 2.5
    assert data["holdings"][0]["cost_basis"] == 250.0


def test_cash_response_includes_balance_and_recent_transactions(client, monkeypatch):
    rows = [{
        "id": "cash-1",
        "timestamp": "2026-08-29T10:00:00",
        "transaction_type": "deposit",
        "amount": 125.0,
        "balance_after": 125.0,
        "note": "opening balance",
    }]
    monkeypatch.setattr(app_mod, "get_cash_balance", lambda: 125.0)
    monkeypatch.setattr(app_mod, "get_recent_cash_transactions", lambda limit: rows)

    res = client.get("/api/cash")

    assert res.status_code == 200
    assert res.get_json() == {"balance": 125.0, "transactions": rows}


def test_cash_post_logs_transaction(client, monkeypatch):
    stored = {
        "id": "cash-1",
        "timestamp": "2026-08-29T10:00:00",
        "transaction_type": "deposit",
        "amount": 125.0,
        "balance_after": 125.0,
        "note": "opening balance",
    }
    mock_insert = MagicMock(return_value=stored)
    monkeypatch.setattr(app_mod, "insert_cash_transaction", mock_insert)
    monkeypatch.setattr(app_mod.uuid, "uuid4", lambda: "cash-1")

    res = client.post("/api/cash", json={
        "transaction_type": "deposit",
        "amount": 125.0,
        "note": "opening balance",
    })

    assert res.status_code == 200
    assert res.get_json() == {"success": True, "transaction": stored, "balance": 125.0}
    assert mock_insert.call_args.args[0]["transaction_type"] == "deposit"
    assert mock_insert.call_args.args[0]["amount"] == 125.0


def test_cash_post_rejects_zero_amount(client):
    res = client.post("/api/cash", json={
        "transaction_type": "deposit",
        "amount": 0,
    })

    assert res.status_code == 400
    assert res.get_json()["error"] == "amount must be a non-zero number"


def test_trade_does_not_mutate_cash(client, monkeypatch):
    monkeypatch.setattr(app_mod, "get_holding", lambda ticker: {
        "ticker": "MSFT",
        "bucket": "Diversified",
        "asset_type": "stock",
        "qty": 1.0,
        "avg_buy": 100.0,
    })
    monkeypatch.setattr(app_mod, "upsert_holding", MagicMock())
    monkeypatch.setattr(app_mod, "insert_trade", MagicMock())
    cash_insert = MagicMock()
    monkeypatch.setattr(app_mod, "insert_cash_transaction", cash_insert)

    res = client.post("/api/trade", json={
        "side": "buy",
        "ticker": "MSFT",
        "qty": 1.0,
        "price": 120.0,
    })

    assert res.status_code == 200
    assert cash_insert.call_count == 0


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
