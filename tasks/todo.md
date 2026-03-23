# Active Task Plan

Updated each session. Mark items complete as you go.

---

## Session: 2026-02-26

### Review CLAUDE.md changes + AAPL trade

- [x] Read CLAUDE.md changes (macro sentiment, simplicity rules, task management, self-improvement loop)
- [x] Verify AAPL trade logged correctly in portfolio/local.py and data/trades.json
- [x] Fix test_decision_engine.py — add `macro_sentiment` ({}) as 4th arg to all `build_context` / `get_decision` calls
- [x] Fix test_main.py — add `get_macro_sentiment` mock to `_patch_pipeline`
- [x] Create tasks/lessons.md with seed lessons + new lessons from this session
- [x] Create tasks/todo.md
- [x] Run full test suite — confirm all pass

---

## Session: 2026-03-23

### Observability — JSONL logging, daily diff, log review script

- [x] Create `modules/run_logger.py` — RunLogger class (Task 1 + Task 2 + Task 3 Option B)
  - `start_run(tickers)` — init run record with UUID v4 run_id
  - `log_step(step_name, data)` — merge data into named step
  - `finalise(status, error)` — write to runs.jsonl, emit stdout, trigger diff
  - `_compute_and_write_diff()` — compare vs yesterday, write diffs.jsonl, emit stdout
  - `_call_drift_api()` — Claude Haiku call for reasoning drift summary
  - `extract_final_signal()` — parse decision text for buy/sell/hold
- [x] Create `scripts/review_logs.py` — CLI log review (Task 4)
  - `--last N`, `--date YYYY-MM-DD`, `--flips-only` flags
  - Stdlib only, line-by-line JSONL reading
- [x] Modify `main.py` `run_daily_briefing()` to integrate RunLogger
  - Add `build_context` to imports from `modules.decision_engine`
  - Wrap fetch / analyse / format steps with log_step calls
  - Call finalise("success") at end, finalise("error", ...) at early returns
- [x] Smoke-test: confirm `logs/runs.jsonl` is written, diffs.jsonl baseline correct, review script works
