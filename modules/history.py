"""Saves and loads portfolio snapshots to SQLite for performance tracking."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.database import get_connection


def _row_to_snapshot(row) -> dict:
    """Convert a SQLite Row from the snapshots table into a snapshot dict."""
    return {
        "date":          row["date"],
        "timestamp":     row["timestamp"],
        "total_value":   row["total_value"],
        "total_cost":    row["total_cost"],
        "total_pnl_usd": row["total_pnl_usd"],
        "total_pnl_pct": row["total_pnl_pct"],
        "crypto_weight": row["crypto_weight"],
        "bucket_values": json.loads(row["bucket_values"]),
        "holdings":      json.loads(row["holdings"]),
    }


def save_snapshot(portfolio_state: dict) -> None:
    """Build a snapshot from portfolio_state and insert it into the snapshots table.

    Skips saving if a snapshot for today's date already exists (PRIMARY KEY dedup).

    Args:
        portfolio_state: The dict returned by modules/portfolio.calculate_portfolio().
    """
    today     = datetime.now().strftime("%Y-%m-%d")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    holdings_summary = {
        ticker: {
            "current_value": data["current_value"],
            "pnl_pct":       data["pnl_pct"],
            "pnl_usd":       data["pnl_usd"],
        }
        for ticker, data in portfolio_state.get("holdings", {}).items()
    }

    conn = get_connection()
    cursor = conn.execute("""
        INSERT OR IGNORE INTO snapshots
            (date, timestamp, total_value, total_cost, total_pnl_usd,
             total_pnl_pct, crypto_weight, bucket_values, holdings)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        today,
        timestamp,
        portfolio_state["total_value"],
        portfolio_state["total_cost"],
        portfolio_state["total_pnl_usd"],
        portfolio_state["total_pnl_pct"],
        portfolio_state["crypto_weight"],
        json.dumps(portfolio_state["bucket_values"]),
        json.dumps(holdings_summary),
    ))
    conn.commit()
    conn.close()

    if cursor.rowcount == 0:
        print(f"  ↩ Snapshot already exists for {today} — skipping.")
    else:
        print(f"  ✓ Snapshot saved {today} — total: ${portfolio_state['total_value']:,.2f}")


def load_history() -> list:
    """Return all snapshots oldest-first.

    Returns:
        List of snapshot dicts. Empty list if no snapshots exist.
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM snapshots ORDER BY date ASC").fetchall()
    conn.close()
    return [_row_to_snapshot(r) for r in rows]


def get_snapshot_by_date(date_str: str) -> dict | None:
    """Return the snapshot for a specific date, or None if not found.

    Args:
        date_str: Date in YYYY-MM-DD format e.g. "2026-02-23".
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM snapshots WHERE date = ?", (date_str,)
    ).fetchone()
    conn.close()
    return _row_to_snapshot(row) if row else None


def get_last_snapshot() -> dict | None:
    """Return the most recent snapshot, or None if no snapshots exist."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM snapshots ORDER BY date DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return _row_to_snapshot(row) if row else None


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
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    if total < 2:
        conn.close()
        return {}

    first_row  = conn.execute("SELECT * FROM snapshots ORDER BY date ASC  LIMIT 1").fetchone()
    latest_row = conn.execute("SELECT * FROM snapshots ORDER BY date DESC LIMIT 1").fetchone()

    latest = _row_to_snapshot(latest_row)
    first  = _row_to_snapshot(first_row)

    # Since inception — use cost-adjusted P&L, not value vs first snapshot.
    # Comparing total_value snapshots inflates the figure when new capital is
    # deployed, because the capital addition itself shows up as a "gain".
    since_inception_usd = latest["total_pnl_usd"]
    since_inception_pct = latest["total_pnl_pct"]

    # Last 7 days — measure change in P&L relative to 7-days-ago cost basis.
    seven_days_ago_str = (
        datetime.strptime(latest["date"], "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")
    seven_row = conn.execute(
        "SELECT * FROM snapshots WHERE date = ?", (seven_days_ago_str,)
    ).fetchone()
    conn.close()

    last_7_days_pct: float | None = None
    if seven_row:
        seven_snap = _row_to_snapshot(seven_row)
        if seven_snap.get("total_cost"):
            pnl_change = latest["total_pnl_usd"] - seven_snap["total_pnl_usd"]
            last_7_days_pct = round(
                (pnl_change / seven_snap["total_cost"]) * 100, 2
            )

    holdings = latest.get("holdings", {})
    best_ticker  = max(holdings, key=lambda t: holdings[t]["pnl_pct"], default=None)
    worst_ticker = min(holdings, key=lambda t: holdings[t]["pnl_pct"], default=None)

    return {
        "since_inception_pct": since_inception_pct,
        "since_inception_usd": since_inception_usd,
        "last_7_days_pct":     last_7_days_pct,
        "best_performer":      {"ticker": best_ticker,  "pnl_pct": holdings[best_ticker]["pnl_pct"]}  if best_ticker  else None,
        "worst_performer":     {"ticker": worst_ticker, "pnl_pct": holdings[worst_ticker]["pnl_pct"]} if worst_ticker else None,
        "total_snapshots":     total,
        "first_date":          first["date"],
        "latest_date":         latest["date"],
    }


# ── Manual test ───────────────────────────────────────────────
if __name__ == "__main__":
    print("── load_history ──")
    history = load_history()
    print(f"  {len(history)} snapshot(s) in DB")

    print("\n── get_last_snapshot ──")
    last = get_last_snapshot()
    if last:
        print(f"  {last['date']}  total=${last['total_value']:,.2f}")
    else:
        print("  No snapshots yet.")

    print("\n── get_performance_summary ──")
    summary = get_performance_summary()
    print(json.dumps(summary, indent=2) if summary else "  Not enough history yet.")
