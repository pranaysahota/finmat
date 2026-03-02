# Lessons Learned

Accumulated project-specific lessons. Review this file at the start of each session before writing any code.

---

1. `portfolio.local.py` qty values must be zero before first `trade.py` run —
   non-zero estimates are treated as real positions and corrupt avg_buy.

2. Bucket names are `Diversified / Growth / Crypto` — not `ETFs / Stocks / Crypto`.
   Using old names breaks `check_bucket_drift()` and all snapshot comparisons.

3. `MSFT` is a portfolio holding, not an external benchmark index.
   Do not fetch it separately as a comparison index.

4. `history.py` receives `portfolio_state` from `portfolio.py` — it does not
   read `portfolio.local.py` directly. Never add direct file reads to history.py.

5. Sentiment runs on stock tickers only — not crypto. Passing crypto tickers
   to `get_all_sentiment()` wastes API calls and returns noise.

6. `portfolio.local.py` must be rewritten using Python's `ast` module —
   never string replacement. String replacement breaks on values that appear
   in comments and produces malformed Python.

7. When adding a new parameter to `build_context` or `get_decision`, update
   the corresponding tests immediately — all call sites must include the new arg.
   The `macro_sentiment` parameter (added between `bucket_drift` and `sentiment`)
   broke all test calls that previously used 5 positional args.

8. `get_macro_sentiment` must be included in `_patch_pipeline` in `test_main.py`
   so that `run_daily_briefing()` tests remain isolated and don't make real
   network or API calls.
