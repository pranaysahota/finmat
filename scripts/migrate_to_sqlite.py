"""One-time migration: portfolio/local.py + data/trades.json → SQLite.

Idempotent — safe to run multiple times. Existing rows are skipped.
Run from project root: python scripts/migrate_to_sqlite.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from modules.database import init_db, get_connection, is_migration_applied, mark_migration_applied

MIGRATION_VERSION = 1
MIGRATION_NAME = "initial_json_to_sqlite"


def _load_portfolio_from_file() -> dict:
    """Load PORTFOLIO directly from portfolio/local.py (bypasses SQLite)."""
    import importlib.util
    portfolio_file = ROOT / "portfolio" / "local.py"
    spec = importlib.util.spec_from_file_location("portfolio_local_migration", portfolio_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PORTFOLIO


def migrate_holdings() -> int:
    """Migrate holdings from portfolio/local.py into the holdings table."""
    portfolio = _load_portfolio_from_file()
    conn = get_connection()
    count = 0

    for bucket, assets in portfolio.items():
        for ticker, asset in assets.items():
            existing = conn.execute(
                "SELECT ticker FROM holdings WHERE ticker = ?", (ticker,)
            ).fetchone()
            if existing:
                print(f"  ⏭  {ticker} already exists — skipping")
                continue

            conn.execute("""
                INSERT INTO holdings (ticker, bucket, asset_type, qty, avg_buy, allocation_usd, bucket_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker, bucket, asset["type"], asset["qty"],
                asset["avg_buy"], asset.get("allocation_usd", 0),
                asset.get("bucket_pct", 0),
            ))
            count += 1
            print(f"  ✓  {ticker} ({bucket}) — qty={asset['qty']}, avg_buy={asset['avg_buy']}")

    conn.commit()
    conn.close()
    return count


def migrate_trades() -> int:
    """Migrate trades from data/trades.json into the trades table."""
    trades_file = ROOT / "data" / "trades.json"
    if not trades_file.exists():
        print("  ⚠️  data/trades.json not found — skipping trades migration")
        return 0

    trades = json.loads(trades_file.read_text())
    conn = get_connection()
    count = 0

    for t in trades:
        existing = conn.execute(
            "SELECT id FROM trades WHERE id = ?", (t["id"],)
        ).fetchone()
        if existing:
            print(f"  ⏭  trade {t['id'][:8]}… already exists — skipping")
            continue

        side = t.get("side", "buy")
        qty = t.get("qty_bought") or t.get("qty_sold", 0)
        price = t.get("price_paid") or t.get("price_received", 0)
        trade_value = t.get("trade_value") or t.get("total_proceeds") or round(qty * price, 2)

        conn.execute("""
            INSERT INTO trades (id, timestamp, side, ticker, bucket, asset_type,
                                qty, price, trade_value, new_qty, new_avg_buy,
                                gross_pnl, cgt_estimate, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t["id"], t["timestamp"], side, t["ticker"], t["bucket"], t["type"],
            qty, price, trade_value,
            t.get("new_qty"), t.get("new_avg_buy"),
            t.get("gross_pnl"), t.get("cgt_estimate"),
            t.get("source", "Revolut"),
        ))
        count += 1
        print(f"  ✓  {side.upper()} {t['ticker']} — {qty} @ ${price}")

    conn.commit()
    conn.close()
    return count


def main() -> None:
    print("\n── SQLite Migration ──\n")

    print("Initialising database…")
    init_db()
    print(f"  ✓  Database ready at data/finmat.db\n")

    if is_migration_applied(MIGRATION_VERSION):
        print(f"  ⏭  Migration v{MIGRATION_VERSION} ({MIGRATION_NAME}) already applied — nothing to do.\n")
        return

    print("Migrating holdings…")
    h = migrate_holdings()
    print(f"  → {h} holdings migrated\n")

    print("Migrating trades…")
    t = migrate_trades()
    print(f"  → {t} trades migrated\n")

    mark_migration_applied(MIGRATION_VERSION, MIGRATION_NAME)
    print("✅ Migration complete.\n")


if __name__ == "__main__":
    main()
