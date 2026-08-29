"""Flask REST API for the finmat portfolio UI.

Serves a single-page frontend and exposes endpoints that reuse
the existing portfolio calculation logic, backed by SQLite.
Protected by Basic Auth when DASHBOARD_PASSWORD is set.
"""

import os
import secrets
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path so modules/ and config.py are importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

from config import BUCKET_TARGETS, CRYPTO_ACTIVE, load_portfolio
from modules.database import get_all_holdings, get_holding, get_recent_trades, insert_trade, upsert_holding
from modules.portfolio import calculate_portfolio
from modules.price_fetcher import get_all_prices
from trade import _calc_cgt, _normalise_ticker

VALID_BUCKETS = {"Diversified", "Growth", "Crypto"}
VALID_TYPES = {"stock", "crypto"}

app = Flask(__name__, static_folder="static")


# ── Basic Auth ───────────────────────────────────────────────────

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "finmat")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")


def _check_auth(username: str, password: str) -> bool:
    """Verify credentials using constant-time comparison."""
    return (
        secrets.compare_digest(username, DASHBOARD_USER)
        and secrets.compare_digest(password, DASHBOARD_PASSWORD)
    )


@app.before_request
def _enforce_auth():
    """Apply Basic Auth to all routes when DASHBOARD_PASSWORD is set."""
    if not DASHBOARD_PASSWORD:
        return
    auth = request.authorization
    if not auth or not _check_auth(auth.username, auth.password):
        return Response(
            "Unauthorized", 401,
            {"WWW-Authenticate": 'Basic realm="finmat"'},
        )


# ── Frontend ─────────────────────────────────────────────────────

@app.route("/")
def root():
    """Redirect root to the dashboard."""
    return redirect("/finmat/dashboard.html")


@app.route("/finmat/dashboard.html")
def dashboard():
    """Serve the single-page UI."""
    return send_from_directory(app.static_folder, "index.html")


# ── REST API ─────────────────────────────────────────────────────

@app.route("/api/portfolio")
def api_portfolio():
    """Return full portfolio state with live prices."""
    try:
        portfolio, state = _load_portfolio_state()

        # Flatten holdings into a sorted list, skip zero-qty positions
        holdings_list = []
        for ticker, data in state["holdings"].items():
            if data["current_value"] == 0:
                continue
            holdings_list.append({
                "ticker": ticker,
                "bucket": data["bucket"],
                "avg_buy": _get_avg_buy(portfolio, ticker),
                "current_price": data["current_price"],
                "current_value": data["current_value"],
                "cost_basis": data["cost_basis"],
                "pnl_pct": data["pnl_pct"],
                "pnl_usd": data["pnl_usd"],
            })

        bucket_order = {"Diversified": 0, "Growth": 1, "Crypto": 2}
        holdings_list.sort(key=lambda h: (bucket_order.get(h["bucket"], 9), h["ticker"]))

        return jsonify({
            "total_value": state["total_value"],
            "total_cost": state["total_cost"],
            "total_pnl_usd": state["total_pnl_usd"],
            "total_pnl_pct": state["total_pnl_pct"],
            "bucket_weights": state["bucket_weights"],
            "bucket_targets": BUCKET_TARGETS,
            "holdings": holdings_list,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/portfolio/summary")
def api_portfolio_summary():
    """Return portfolio totals and bucket weights with live prices."""
    try:
        _, state = _load_portfolio_state()
        return jsonify(_portfolio_summary(state))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/tickers")
def api_tickers():
    """Return list of tickers currently in the portfolio."""
    try:
        portfolio = load_portfolio()
        tickers = []
        for bucket, assets in portfolio.items():
            if bucket == "Crypto" and not CRYPTO_ACTIVE:
                continue
            for ticker, asset in assets.items():
                if asset["qty"] > 0:
                    tickers.append({
                        "ticker": ticker,
                        "bucket": bucket,
                        "type": asset["type"],
                        "qty": asset["qty"],
                    })
        return jsonify(tickers)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/trades/recent")
def api_recent_trades():
    """Return the last 5 trades from SQLite."""
    try:
        trades = get_recent_trades(5)
        return jsonify(trades)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/trade", methods=["POST"])
def api_trade():
    """Log a buy or sell trade.

    Expects JSON body:
      Buy:  {"side": "buy",  "ticker": "NVDA", "qty": 2, "price": 130.50}
      Sell: {"side": "sell", "ticker": "NVDA", "qty": 1, "price": 145.00}

    For new tickers (buy only):
      {"side": "buy", "ticker": "COIN", "qty": 5, "price": 200,
       "bucket": "Growth", "asset_type": "stock"}
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        side = data.get("side")
        ticker_raw = data.get("ticker", "").strip()
        qty = data.get("qty")
        price = data.get("price")

        if side not in ("buy", "sell"):
            return jsonify({"error": "side must be 'buy' or 'sell'"}), 400
        if not ticker_raw:
            return jsonify({"error": "ticker is required"}), 400
        if not isinstance(qty, (int, float)) or qty <= 0:
            return jsonify({"error": "qty must be a positive number"}), 400
        if not isinstance(price, (int, float)) or price <= 0:
            return jsonify({"error": "price must be a positive number"}), 400

        if side == "sell":
            return _handle_sell(ticker_raw, qty, price)
        else:
            return _handle_buy(ticker_raw, qty, price, data)

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Trade helpers ────────────────────────────────────────────────

def _resolve_ticker(ticker_raw: str) -> tuple[str, dict | None]:
    """Try to find a ticker in the DB (uppercase then lowercase)."""
    for variant in (ticker_raw.upper(), ticker_raw.lower()):
        holding = get_holding(variant)
        if holding:
            return variant, holding
    return ticker_raw, None


def _handle_buy(ticker_raw: str, qty: float, price: float, data: dict):
    """Process a buy trade and return JSON response."""
    ticker, holding = _resolve_ticker(ticker_raw)

    if holding is None:
        # New ticker — bucket and asset_type required
        bucket = data.get("bucket")
        asset_type = data.get("asset_type")
        if bucket not in VALID_BUCKETS:
            return jsonify({"error": f"bucket must be one of: {', '.join(sorted(VALID_BUCKETS))}"}), 400
        if asset_type not in VALID_TYPES:
            return jsonify({"error": f"asset_type must be one of: {', '.join(sorted(VALID_TYPES))}"}), 400
        ticker = _normalise_ticker(ticker_raw, asset_type)
        old_qty = 0.0
        old_avg = 0.0
    else:
        bucket = holding["bucket"]
        asset_type = holding["asset_type"]
        ticker = holding["ticker"]
        old_qty = holding["qty"]
        old_avg = holding["avg_buy"]

    new_qty = round(old_qty + qty, 8)
    new_avg = price if old_qty == 0 else round(
        (old_qty * old_avg + qty * price) / new_qty, 2
    )
    trade_value = round(qty * price, 2)

    upsert_holding(ticker, bucket, asset_type, new_qty, new_avg)

    trade_record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "side": "buy",
        "ticker": ticker,
        "bucket": bucket,
        "asset_type": asset_type,
        "qty": qty,
        "price": price,
        "trade_value": trade_value,
        "new_qty": new_qty,
        "new_avg_buy": new_avg,
        "source": "Revolut",
    }
    insert_trade(trade_record)

    return jsonify({"success": True, "trade": trade_record})


def _handle_sell(ticker_raw: str, qty: float, price: float):
    """Process a sell trade and return JSON response."""
    ticker, holding = _resolve_ticker(ticker_raw)

    if holding is None or holding["qty"] == 0:
        return jsonify({"error": f"{ticker} not found in portfolio or qty is zero"}), 400

    current_qty = holding["qty"]
    avg_buy = holding["avg_buy"]
    bucket = holding["bucket"]
    asset_type = holding["asset_type"]
    ticker = holding["ticker"]

    if qty > current_qty:
        return jsonify({"error": f"Cannot sell {qty} — you hold {current_qty}"}), 400

    total_cost = round(avg_buy * qty, 2)
    total_proceeds = round(price * qty, 2)
    gross_pnl = round(total_proceeds - total_cost, 2)
    cgt_owed = _calc_cgt(gross_pnl)
    remaining_qty = round(current_qty - qty, 8)

    new_avg_buy = 0.0 if remaining_qty == 0.0 else avg_buy
    upsert_holding(ticker, bucket, asset_type, remaining_qty, new_avg_buy)

    trade_record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "side": "sell",
        "ticker": ticker,
        "bucket": bucket,
        "asset_type": asset_type,
        "qty": qty,
        "price": price,
        "trade_value": total_proceeds,
        "new_qty": remaining_qty,
        "new_avg_buy": new_avg_buy,
        "gross_pnl": gross_pnl,
        "cgt_estimate": cgt_owed,
        "source": "Revolut",
    }
    insert_trade(trade_record)

    return jsonify({"success": True, "trade": trade_record})


# ── Digest trigger ──────────────────────────────────────────────

# Guard against concurrent digest runs
_digest_lock = threading.Lock()


@app.route("/api/digest", methods=["POST"])
def api_digest():
    """Trigger the daily digest pipeline in a background thread.

    Returns immediately with 202 Accepted. The digest runs asynchronously
    and sends results to Telegram/email as usual.
    """
    if not _digest_lock.acquire(blocking=False):
        return jsonify({"error": "Digest is already running"}), 409

    def _run():
        try:
            from main import run_daily_digest
            run_daily_digest()
        finally:
            _digest_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "Digest started"}), 202


# ── Helpers ──────────────────────────────────────────────────────

def _load_portfolio_state() -> tuple[dict, dict]:
    """Load the portfolio and calculate its state using live prices."""
    portfolio = load_portfolio()
    prices = get_all_prices(portfolio)
    return portfolio, calculate_portfolio(prices, portfolio)


def _portfolio_summary(state: dict) -> dict:
    """Select the compact, API-facing subset of a portfolio state."""
    return {
        "total_value": state["total_value"],
        "total_cost": state["total_cost"],
        "total_pnl_usd": state["total_pnl_usd"],
        "total_pnl_pct": state["total_pnl_pct"],
        "bucket_weights": {
            bucket: state["bucket_weights"].get(bucket, 0.0)
            for bucket in BUCKET_TARGETS
        },
    }


def _get_avg_buy(portfolio: dict, ticker: str) -> float:
    """Look up avg_buy for a ticker from the portfolio dict."""
    for bucket, assets in portfolio.items():
        if ticker in assets:
            return assets[ticker]["avg_buy"]
    return 0.0


# ── Entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5001)
