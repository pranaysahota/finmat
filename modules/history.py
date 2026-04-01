"""Saves and loads portfolio snapshots to data/portfolio_history.json for performance tracking."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow direct invocation (python modules/history.py) as well as import
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PATHS

HISTORY_FILE: Path = PATHS["HISTORY_FILE"]
DATA_DIR: Path     = PATHS["DATA_DIR"]


def save_snapshot(portfolio_state: dict) -> None:
    """Build a snapshot from portfolio_state and append it to the history file.

    Skips saving if a snapshot for today's date already exists, preventing
    duplicate entries when the agent restarts mid-day.

    Args:
        portfolio_state: The dict returned by modules/portfolio.calculate_portfolio().
    """
    today     = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    history = load_history()

    if any(s.get("date") == today for s in history):
        print(f"  ↩ Snapshot already exists for {today} — skipping.")
        return

    # Compress holdings to only the fields needed for history
    holdings_summary = {
        ticker: {
            "current_value": data["current_value"],
            "pnl_pct":       data["pnl_pct"],
            "pnl_usd":       data["pnl_usd"],
        }
        for ticker, data in portfolio_state.get("holdings", {}).items()
    }

    snapshot = {
        "date":          today,
        "timestamp":     timestamp,
        "total_value":   portfolio_state["total_value"],
        "total_cost":    portfolio_state["total_cost"],
        "total_pnl_usd": portfolio_state["total_pnl_usd"],
        "total_pnl_pct": portfolio_state["total_pnl_pct"],
        "crypto_weight": portfolio_state["crypto_weight"],
        "bucket_values": portfolio_state["bucket_values"],
        "holdings":      holdings_summary,
    }

    DATA_DIR.mkdir(exist_ok=True)
    history.append(snapshot)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

    print(f"  ✓ Snapshot saved {today} — total: ${portfolio_state['total_value']:,.2f}")


def load_history() -> list:
    """Read and return all snapshots from the history file.

    Returns:
        List of snapshot dicts, oldest first. Empty list if file doesn't exist.
    """
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except json.JSONDecodeError:
        print(f"  ⚠️  Could not parse {HISTORY_FILE} — returning empty history.")
        return []


def get_snapshot_by_date(date_str: str) -> dict | None:
    """Return the snapshot for a specific date, or None if not found.

    Args:
        date_str: Date in YYYY-MM-DD format e.g. "2026-02-23".
    """
    return next(
        (s for s in load_history() if s.get("date") == date_str),
        None,
    )


def get_performance_summary() -> dict:
    """Compare the latest snapshot to inception and to 7 days ago.

    Returns:
        Dict with performance metrics, or empty dict if fewer than 2 snapshots.
        {
            "since_inception_pct":  float,
            "since_inception_usd":  float,
            "last_7_days_pct":      float | None,
            "best_performer":       {"ticker": str, "pnl_pct": float},
            "worst_performer":      {"ticker": str, "pnl_pct": float},
            "total_snapshots":      int,
            "first_date":           str,
            "latest_date":          str,
        }
    """
    history = load_history()

    if len(history) < 2:
        return {}

    first  = history[0]
    latest = history[-1]

    # Since inception — use cost-adjusted P&L, not value vs first snapshot.
    # Comparing total_value snapshots inflates the figure when new capital is
    # deployed (new positions added), because the capital addition itself shows
    # up as a "gain". total_pnl already nets out cost basis correctly.
    since_inception_usd = latest["total_pnl_usd"]
    since_inception_pct = latest["total_pnl_pct"]

    # Last 7 days — measure change in P&L relative to 7-days-ago cost basis.
    seven_days_ago_str = (
        datetime.strptime(latest["date"], "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")
    seven_days_snap    = get_snapshot_by_date(seven_days_ago_str)

    last_7_days_pct: float | None = None
    if seven_days_snap and seven_days_snap.get("total_cost"):
        pnl_change = latest["total_pnl_usd"] - seven_days_snap["total_pnl_usd"]
        last_7_days_pct = round(
            (pnl_change / seven_days_snap["total_cost"]) * 100, 2
        )

    # Best and worst performer from the latest snapshot
    holdings = latest.get("holdings", {})
    best_ticker  = max(holdings, key=lambda t: holdings[t]["pnl_pct"], default=None)
    worst_ticker = min(holdings, key=lambda t: holdings[t]["pnl_pct"], default=None)

    return {
        "since_inception_pct": since_inception_pct,
        "since_inception_usd": since_inception_usd,
        "last_7_days_pct":     last_7_days_pct,
        "best_performer":      {"ticker": best_ticker,  "pnl_pct": holdings[best_ticker]["pnl_pct"]}  if best_ticker  else None,
        "worst_performer":     {"ticker": worst_ticker, "pnl_pct": holdings[worst_ticker]["pnl_pct"]} if worst_ticker else None,
        "total_snapshots":     len(history),
        "first_date":          first["date"],
        "latest_date":         latest["date"],
    }


def get_last_snapshot() -> dict | None:
    """Return the most recent snapshot, or None if history is empty."""
    history = load_history()
    return history[-1] if history else None


# ── Manual test ───────────────────────────────────────────────
if __name__ == "__main__":
    import json

    # Inject a fake portfolio_state to test save + load
    mock_state = {
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

    print("── save_snapshot ──")
    save_snapshot(mock_state)

    print("\n── load_history ──")
    history = load_history()
    print(f"  {len(history)} snapshot(s) on file")

    print("\n── get_last_snapshot ──")
    last = get_last_snapshot()
    print(f"  {last['date']}  total=${last['total_value']}")

    print("\n── get_performance_summary ──")
    summary = get_performance_summary()
    print(json.dumps(summary, indent=2) if summary else "  Not enough history yet.")
