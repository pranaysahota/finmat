"""Calculates portfolio value, P&L per holding, and checks risk rules against configured thresholds."""

import sys
from pathlib import Path

# Allow direct invocation (python modules/portfolio.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import BUCKET_TARGETS, PORTFOLIO, RULES


def calculate_portfolio(prices: dict) -> dict:
    """Calculate the full portfolio state from holdings and live prices.

    Reads qty and avg_buy for every ticker from PORTFOLIO (imported from
    portfolio/local.py via config.py), pairs them with the prices dict,
    and produces the complete portfolio state dict.

    Pure calculation — no I/O, no API calls, no side effects.
    Any ticker whose price is None is skipped with a printed warning so
    that a single failed price fetch does not corrupt overall totals.

    Args:
        prices: Flat {ticker: price} dict as returned by
                modules.price_fetcher.get_all_prices().

    Returns:
        portfolio_state dict — see CLAUDE.md for the full shape.
    """
    holdings:      dict = {}
    bucket_values: dict = {bucket: 0.0 for bucket in PORTFOLIO}

    for bucket, assets in PORTFOLIO.items():
        for ticker, asset in assets.items():
            price = prices.get(ticker)
            if price is None:
                print(f"  ⚠️  {ticker}: price unavailable — excluded from calculations")
                continue

            qty       = asset["qty"]
            avg_buy   = asset["avg_buy"]

            current_value = round(qty * price,   2)
            cost_basis    = round(qty * avg_buy, 2)
            pnl_usd       = round(current_value - cost_basis, 2)
            pnl_pct       = round((pnl_usd / cost_basis) * 100, 2) if cost_basis else 0.0

            holdings[ticker] = {
                "current_price": price,
                "current_value": current_value,
                "cost_basis":    cost_basis,
                "pnl_pct":       pnl_pct,
                "pnl_usd":       pnl_usd,
                "bucket":        bucket,
            }

            bucket_values[bucket] = round(bucket_values[bucket] + current_value, 2)

    total_value   = round(sum(h["current_value"] for h in holdings.values()), 2)
    total_cost    = round(sum(h["cost_basis"]    for h in holdings.values()), 2)
    total_pnl_usd = round(total_value - total_cost, 2)
    total_pnl_pct = round((total_pnl_usd / total_cost) * 100, 2) if total_cost else 0.0

    crypto_value  = bucket_values.get("Crypto", 0.0)
    crypto_weight = round((crypto_value / total_value) * 100, 2) if total_value else 0.0

    bucket_weights = {
        bucket: round((val / total_value) * 100, 2) if total_value else 0.0
        for bucket, val in bucket_values.items()
    }

    return {
        "total_value":    total_value,
        "total_cost":     total_cost,
        "total_pnl_usd":  total_pnl_usd,
        "total_pnl_pct":  total_pnl_pct,
        "crypto_weight":  crypto_weight,
        "bucket_values":  bucket_values,
        "bucket_weights": bucket_weights,
        "holdings":       holdings,
    }


def check_rules(portfolio_state: dict) -> list[dict]:
    """Check portfolio state against risk rules and return any triggered alerts.

    Evaluates per-holding stop_loss and take_profit thresholds, and the
    portfolio-level crypto_weight limit. The benchmark key in RULES is an
    internal reference for the decision engine — it does not trigger an alert.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().

    Returns:
        List of triggered alert dicts with keys: level, ticker, rule, message.
        Empty list if nothing is triggered.
    """
    alerts: list[dict] = []

    for ticker, data in portfolio_state.get("holdings", {}).items():
        pnl_pct = data["pnl_pct"]

        if pnl_pct <= RULES["stop_loss_pct"]:
            alerts.append({
                "level":   "CRITICAL",
                "ticker":  ticker,
                "rule":    "stop_loss",
                "message": (
                    f"🔴 {ticker} is down {pnl_pct:.1f}% — "
                    f"stop-loss threshold breached ({RULES['stop_loss_pct']}%)"
                ),
            })

        elif pnl_pct >= RULES["take_profit_pct"]:
            alerts.append({
                "level":   "HIGH",
                "ticker":  ticker,
                "rule":    "take_profit",
                "message": (
                    f"🟢 {ticker} is up {pnl_pct:.1f}% — "
                    f"take-profit threshold reached ({RULES['take_profit_pct']}%)"
                ),
            })

    crypto_weight = portfolio_state.get("crypto_weight", 0.0)
    if crypto_weight > RULES["crypto_max_weight"]:
        alerts.append({
            "level":   "MEDIUM",
            "ticker":  "Crypto",
            "rule":    "crypto_weight",
            "message": (
                f"🟡 Crypto weight is {crypto_weight:.1f}% — "
                f"exceeds max {RULES['crypto_max_weight']}%"
            ),
        })

    return alerts


def check_bucket_drift(portfolio_state: dict) -> list[dict]:
    """Detect buckets that have drifted beyond the allowed tolerance from targets.

    Compares actual bucket_weights against BUCKET_TARGETS. A MEDIUM alert is
    raised for any bucket where the absolute drift exceeds
    RULES["bucket_drift_pct"] percentage points.

    Args:
        portfolio_state: Dict as returned by calculate_portfolio().

    Returns:
        List of MEDIUM drift alert dicts. Empty list if all buckets are
        within tolerance.
    """
    alerts:    list[dict] = []
    threshold: float      = RULES["bucket_drift_pct"]
    bucket_weights        = portfolio_state.get("bucket_weights", {})

    for bucket, target_pct in BUCKET_TARGETS.items():
        actual_pct = bucket_weights.get(bucket, 0.0)
        drift      = round(actual_pct - target_pct, 2)

        if abs(drift) > threshold:
            direction = "overweight" if drift > 0 else "underweight"
            alerts.append({
                "level":   "MEDIUM",
                "ticker":  bucket,
                "rule":    "bucket_drift",
                "message": (
                    f"📐 {bucket} bucket is {direction}: "
                    f"{actual_pct:.1f}% actual vs {target_pct}% target "
                    f"(drift: {drift:+.1f}pp)"
                ),
            })

    return alerts


# ── Manual test ───────────────────────────────────────────────
if __name__ == "__main__":
    # Mock prices for a sanity check without a live API call
    mock_prices = {
        "MSFT":     430.00, "AAPL":  230.00, "JPM":  250.00,
        "JNJ":      155.00, "ASML":  700.00, "BRK.B": 480.00, "XOM": 120.00,
        "GOOG":     180.00, "NVDA":  140.00,
        "bitcoin": 98000.00, "ethereum": 2800.00,
    }

    print("\n── calculate_portfolio ──\n")
    state = calculate_portfolio(mock_prices)
    print(f"  Total value:   ${state['total_value']:,.2f}")
    print(f"  Total cost:    ${state['total_cost']:,.2f}")
    print(f"  P&L:           ${state['total_pnl_usd']:,.2f} ({state['total_pnl_pct']:+.2f}%)")
    print(f"  Crypto weight: {state['crypto_weight']:.1f}%")
    print(f"\n  Bucket weights:")
    for bucket, weight in state["bucket_weights"].items():
        print(f"    {bucket:<15} {weight:.1f}%  (target {BUCKET_TARGETS[bucket]}%)")
    print(f"\n  Holdings:")
    for ticker, data in state["holdings"].items():
        print(f"    {ticker:<12} ${data['current_value']:>10,.2f}  {data['pnl_pct']:+.2f}%")

    print("\n── check_rules ──\n")
    rule_alerts = check_rules(state)
    for alert in rule_alerts:
        print(f"  [{alert['level']}] {alert['message']}")
    if not rule_alerts:
        print("  No rules triggered.")

    print("\n── check_bucket_drift ──\n")
    drift_alerts = check_bucket_drift(state)
    for alert in drift_alerts:
        print(f"  [{alert['level']}] {alert['message']}")
    if not drift_alerts:
        print("  All buckets within targets.")
