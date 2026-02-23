# Copy this file to portfolio.local.py and fill in your real values.
# portfolio.local.py is gitignored and will never be committed.

PORTFOLIO = {

    # ── BUCKET 1: ETFs ───────────────────────────────────────
    "ETFs": {
        "TICKER1": {
            "type":           "stock",    # "stock" for equities/ETFs, "crypto" for coins
            "qty":            0.00,       # number of shares held
            "avg_buy":        0.00,       # average purchase price per share (USD)
            "allocation_usd": 0.00,       # target dollar allocation for this asset
            "bucket_pct":     0,          # % of this bucket allocated to this ticker
        },
        "TICKER2": {
            "type":           "stock",
            "qty":            0.00,
            "avg_buy":        0.00,
            "allocation_usd": 0.00,
            "bucket_pct":     0,
        },
    },

    # ── BUCKET 2: Stocks ─────────────────────────────────────
    "Stocks": {
        "TICKER3": {
            "type":           "stock",
            "qty":            0.00,
            "avg_buy":        0.00,
            "allocation_usd": 0.00,
            "bucket_pct":     0,
        },
    },

    # ── BUCKET 3: Crypto ─────────────────────────────────────
    "Crypto": {
        "bitcoin": {
            "type":           "crypto",   # use CoinGecko coin ID, e.g. "bitcoin", "ethereum"
            "qty":            0.0000,
            "avg_buy":        0.00,
            "allocation_usd": 0.00,
            "bucket_pct":     0,
        },
    },
}
