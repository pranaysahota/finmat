"""SQLite database module — single source of truth for holdings and trades.

Replaces portfolio/local.py (AST-managed Python file) and data/trades.json
with a single finmat.db file in the data/ directory.
"""

import os
import sqlite3
from pathlib import Path

# Mirror config.py logic — resolve /data (Fly.io volume) vs data/ (local)
# Cannot import from config.py here since config.py imports from this module.
_DATA_DIR = Path("/data") if os.path.exists("/data") else Path(__file__).parent.parent / "data"
DB_PATH = _DATA_DIR / "finmat.db"


def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS migrations (
            version   INTEGER PRIMARY KEY,
            name      TEXT NOT NULL,
            applied   TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS holdings (
            ticker         TEXT PRIMARY KEY,
            bucket         TEXT NOT NULL CHECK(bucket IN ('Diversified', 'Growth', 'Crypto')),
            asset_type     TEXT NOT NULL CHECK(asset_type IN ('stock', 'crypto')),
            qty            REAL NOT NULL DEFAULT 0,
            avg_buy        REAL NOT NULL DEFAULT 0.0,
            allocation_usd REAL NOT NULL DEFAULT 0,
            bucket_pct     REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS trades (
            id             TEXT PRIMARY KEY,
            timestamp      TEXT NOT NULL,
            side           TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
            ticker         TEXT NOT NULL,
            bucket         TEXT NOT NULL,
            asset_type     TEXT NOT NULL,
            qty            REAL NOT NULL,
            price          REAL NOT NULL,
            trade_value    REAL NOT NULL,
            new_qty        REAL,
            new_avg_buy    REAL,
            gross_pnl      REAL,
            cgt_estimate   REAL,
            source         TEXT NOT NULL DEFAULT 'Revolut'
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            date          TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            total_value   REAL NOT NULL,
            total_cost    REAL NOT NULL,
            total_pnl_usd REAL NOT NULL,
            total_pnl_pct REAL NOT NULL,
            crypto_weight REAL NOT NULL,
            bucket_values TEXT NOT NULL,
            holdings      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlist (
            ticker     TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


# ── Migrations ───────────────────────────────────────────────────

def is_migration_applied(version: int) -> bool:
    """Check if a migration version has already been applied."""
    conn = get_connection()
    row = conn.execute(
        "SELECT version FROM migrations WHERE version = ?", (version,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_migration_applied(version: int, name: str) -> None:
    """Record that a migration has been applied."""
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO migrations (version, name) VALUES (?, ?)",
        (version, name),
    )
    conn.commit()
    conn.close()


# ── Holdings CRUD ────────────────────────────────────────────────

def get_all_holdings() -> dict:
    """Return holdings as the PORTFOLIO dict structure expected by the rest of the app.

    Returns:
        {bucket: {ticker: {type, qty, avg_buy, allocation_usd, bucket_pct}}}
    """
    conn = get_connection()
    rows = conn.execute("SELECT * FROM holdings WHERE qty > 0 ORDER BY bucket, ticker").fetchall()
    conn.close()

    portfolio: dict = {}
    for row in rows:
        bucket = row["bucket"]
        if bucket not in portfolio:
            portfolio[bucket] = {}
        portfolio[bucket][row["ticker"]] = {
            "type": row["asset_type"],
            "qty": row["qty"],
            "avg_buy": row["avg_buy"],
            "allocation_usd": row["allocation_usd"],
            "bucket_pct": row["bucket_pct"],
        }
    return portfolio


def upsert_holding(ticker: str, bucket: str, asset_type: str,
                   qty: float, avg_buy: float,
                   allocation_usd: float = 0, bucket_pct: float = 0) -> None:
    """Insert or update a single holding."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO holdings (ticker, bucket, asset_type, qty, avg_buy, allocation_usd, bucket_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            qty = excluded.qty,
            avg_buy = excluded.avg_buy,
            allocation_usd = excluded.allocation_usd,
            bucket_pct = excluded.bucket_pct
    """, (ticker, bucket, asset_type, qty, round(avg_buy, 2), allocation_usd, bucket_pct))
    conn.commit()
    conn.close()


def get_holding(ticker: str) -> dict | None:
    """Return a single holding dict or None if not found."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM holdings WHERE ticker = ?", (ticker,)).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


# ── Trades CRUD ──────────────────────────────────────────────────

def insert_trade(trade: dict) -> None:
    """Insert a trade record."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO trades (id, timestamp, side, ticker, bucket, asset_type,
                            qty, price, trade_value, new_qty, new_avg_buy,
                            gross_pnl, cgt_estimate, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade["id"], trade["timestamp"], trade["side"], trade["ticker"],
        trade["bucket"], trade["asset_type"], trade["qty"], trade["price"],
        trade["trade_value"], trade.get("new_qty"), trade.get("new_avg_buy"),
        trade.get("gross_pnl"), trade.get("cgt_estimate"),
        trade.get("source", "Revolut"),
    ))
    conn.commit()
    conn.close()


def get_recent_trades(limit: int = 5) -> list[dict]:
    """Return the most recent trades, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_realized_pnl() -> float:
    """Return realized P&L from sell trades that stored a gross_pnl value."""
    return get_realized_pnl_breakdown()["pnl"]


def get_realized_pnl_breakdown() -> dict:
    """Return realized profit, loss, and net P&L from sell trades."""
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN gross_pnl > 0 THEN gross_pnl ELSE 0 END), 0) AS profit,
            COALESCE(SUM(CASE WHEN gross_pnl < 0 THEN ABS(gross_pnl) ELSE 0 END), 0) AS loss,
            COALESCE(SUM(gross_pnl), 0) AS pnl
        FROM trades
        WHERE side = 'sell' AND gross_pnl IS NOT NULL
    """).fetchone()
    conn.close()
    return {
        "profit": round(float(row["profit"]), 2),
        "loss": round(float(row["loss"]), 2),
        "pnl": round(float(row["pnl"]), 2),
    }


# ── Watchlist CRUD ────────────────────────────────────────────────

def get_watchlist_tickers() -> list[str]:
    """Return watchlist tickers in display order."""
    conn = get_connection()
    rows = conn.execute("SELECT ticker FROM watchlist ORDER BY ticker").fetchall()
    conn.close()
    return [row["ticker"] for row in rows]


def add_watchlist_ticker(ticker: str) -> str:
    """Add a stock ticker to the watchlist and return its normalized symbol."""
    normalized = ticker.strip().upper()
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO watchlist (ticker) VALUES (?)",
        (normalized,),
    )
    conn.commit()
    conn.close()
    return normalized


def remove_watchlist_ticker(ticker: str) -> bool:
    """Remove a stock ticker from the watchlist. Returns True when removed."""
    normalized = ticker.strip().upper()
    conn = get_connection()
    cur = conn.execute("DELETE FROM watchlist WHERE ticker = ?", (normalized,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0
