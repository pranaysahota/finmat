"""Tests for SQLite database helpers."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.database as db_mod
from modules.database import (  # noqa: E402
    add_watchlist_ticker,
    get_cash_balance,
    get_realized_pnl,
    get_realized_pnl_breakdown,
    get_recent_cash_transactions,
    get_watchlist_tickers,
    init_db,
    insert_cash_transaction,
    insert_trade,
    remove_watchlist_ticker,
)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "finmat.db")
    init_db()


def _trade(trade_id: str, side: str, gross_pnl: float | None = None) -> dict:
    return {
        "id": trade_id,
        "timestamp": "2026-05-29T10:00:00",
        "side": side,
        "ticker": "MSFT",
        "bucket": "Diversified",
        "asset_type": "stock",
        "qty": 1.0,
        "price": 100.0,
        "trade_value": 100.0,
        "new_qty": 0.0 if side == "sell" else 1.0,
        "new_avg_buy": 0.0 if side == "sell" else 100.0,
        "gross_pnl": gross_pnl,
        "source": "Revolut",
    }


def _cash_tx(tx_id: str, transaction_type: str, amount: float, timestamp: str) -> dict:
    return {
        "id": tx_id,
        "timestamp": timestamp,
        "transaction_type": transaction_type,
        "amount": amount,
        "note": "test cash movement",
    }


def test_watchlist_add_list_remove_round_trip():
    assert add_watchlist_ticker(" msft ") == "MSFT"
    assert add_watchlist_ticker("aapl") == "AAPL"
    add_watchlist_ticker("MSFT")

    assert get_watchlist_tickers() == ["AAPL", "MSFT"]
    assert remove_watchlist_ticker("msft") is True
    assert remove_watchlist_ticker("missing") is False
    assert get_watchlist_tickers() == ["AAPL"]


def test_realized_pnl_sums_only_sell_trades_with_gross_pnl():
    insert_trade(_trade("buy-1", "buy", gross_pnl=999.0))
    insert_trade(_trade("sell-1", "sell", gross_pnl=25.25))
    insert_trade(_trade("sell-2", "sell", gross_pnl=-10.10))
    insert_trade(_trade("sell-3", "sell", gross_pnl=None))

    assert get_realized_pnl() == 15.15
    assert get_realized_pnl_breakdown() == {
        "profit": 25.25,
        "loss": 10.10,
        "pnl": 15.15,
    }


def test_realized_pnl_is_zero_without_matching_sells():
    insert_trade(_trade("buy-1", "buy", gross_pnl=None))

    assert get_realized_pnl() == 0.0
    assert get_realized_pnl_breakdown() == {
        "profit": 0.0,
        "loss": 0.0,
        "pnl": 0.0,
    }


def test_cash_balance_defaults_to_zero():
    assert get_cash_balance() == 0.0
    assert get_recent_cash_transactions() == []


def test_cash_transactions_store_signed_amounts_and_running_balance():
    deposit = insert_cash_transaction(
        _cash_tx("cash-1", "deposit", 250.0, "2026-08-29T10:00:00")
    )
    withdrawal = insert_cash_transaction(
        _cash_tx("cash-2", "withdrawal", 40.0, "2026-08-29T11:00:00")
    )
    adjustment = insert_cash_transaction(
        _cash_tx("cash-3", "adjustment", -10.0, "2026-08-29T12:00:00")
    )

    assert deposit["amount"] == 250.0
    assert deposit["balance_after"] == 250.0
    assert withdrawal["amount"] == -40.0
    assert withdrawal["balance_after"] == 210.0
    assert adjustment["amount"] == -10.0
    assert adjustment["balance_after"] == 200.0
    assert get_cash_balance() == 200.0


def test_recent_cash_transactions_are_newest_first():
    insert_cash_transaction(_cash_tx("cash-1", "deposit", 100.0, "2026-08-29T10:00:00"))
    insert_cash_transaction(_cash_tx("cash-2", "deposit", 25.0, "2026-08-29T12:00:00"))
    insert_cash_transaction(_cash_tx("cash-3", "withdrawal", 10.0, "2026-08-29T11:00:00"))

    rows = get_recent_cash_transactions(2)

    assert [row["id"] for row in rows] == ["cash-2", "cash-3"]


def test_cash_transaction_rejects_negative_balance():
    with pytest.raises(ValueError, match="cannot go negative"):
        insert_cash_transaction(_cash_tx("cash-1", "withdrawal", 1.0, "2026-08-29T10:00:00"))
