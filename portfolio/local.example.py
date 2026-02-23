# Copy this file to portfolio/local.py and replace all 0 values
# with your real holdings. portfolio/local.py is gitignored.
# This example file exists only to show the required structure.

PORTFOLIO = {

    # ── BUCKET 1: ETFs ───────────────────────────────────────
    "ETFs": {
        "TICKER1": {
            "type":           "stock",   # "stock" for equities/ETFs, "crypto" for coins
            "qty":            0,         # number of shares held
            "avg_buy":        0.0,       # average purchase price per share (USD)
            "allocation_usd": 0,         # target dollar allocation for this asset
            "bucket_pct":     0,         # this asset's % weight within its bucket
        },
        "TICKER2": {
            "type":           "stock",
            "qty":            0,
            "avg_buy":        0.0,
            "allocation_usd": 0,
            "bucket_pct":     0,
        },
    },

    # ── BUCKET 2: Stocks ─────────────────────────────────────
    "Stocks": {
        "TICKER3": {
            "type":           "stock",
            "qty":            0,
            "avg_buy":        0.0,
            "allocation_usd": 0,
            "bucket_pct":     0,
        },
    },

    # ── BUCKET 3: Crypto ─────────────────────────────────────
    "Crypto": {
        "bitcoin": {
            "type":           "crypto",  # use CoinGecko coin ID: "bitcoin", "ethereum", etc.
            "qty":            0,
            "avg_buy":        0.0,
            "allocation_usd": 0,
            "bucket_pct":     0,
        },
    },
}
