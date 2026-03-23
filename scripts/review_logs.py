#!/usr/bin/env python3
"""CLI tool for reviewing finmat workflow logs from logs/runs.jsonl and logs/diffs.jsonl.

Usage:
    python scripts/review_logs.py --last 7
    python scripts/review_logs.py --date 2026-03-23
    python scripts/review_logs.py --flips-only

All reading is line-by-line — the full JSONL file is never loaded into memory at once.
No external dependencies — stdlib only.
"""

import argparse
import json
import os
import sys
from pathlib import Path


_LOG_DIR = Path(os.environ.get("LOG_DIR", "logs"))
_RUNS_FILE  = _LOG_DIR / "runs.jsonl"
_DIFFS_FILE = _LOG_DIR / "diffs.jsonl"


def _iter_jsonl(path: Path):
    """Yield parsed JSON records from a JSONL file, one line at a time."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _load_diffs_by_run_id() -> dict:
    """Return a dict of today_run_id → diff_record for all diff records."""
    result: dict = {}
    for diff in _iter_jsonl(_DIFFS_FILE):
        run_id = diff.get("today_run_id", "")
        if run_id:
            result[run_id] = diff
    return result


def _sentiment_label_to_signal(label: str) -> str:
    """Map a sentiment label to a one-word signal."""
    upper = label.upper()
    if "BEARISH" in upper:
        return "sell"
    if "BULLISH" in upper:
        return "buy"
    return "hold"


def _collect_runs() -> list[dict]:
    """Read all run records into a list (used for --last / --date lookups)."""
    return list(_iter_jsonl(_RUNS_FILE))


def _has_flips(run: dict, diffs_by_run: dict) -> bool:
    diff = diffs_by_run.get(run.get("run_id", ""))
    return bool(diff and diff.get("signal_changes"))


def _print_run(run: dict, diff: dict | None) -> None:
    """Print a human-readable summary block for one run record."""
    run_id   = (run.get("run_id") or "unknown")[:8]
    run_date = run.get("date",   "unknown")
    status   = run.get("status", "unknown")

    sentiment = (
        run.get("steps", {})
        .get("analyse", {})
        .get("parsed_output", {})
        .get("sentiment", {})
    )
    final_signal = (
        run.get("steps", {})
        .get("format", {})
        .get("final_signal", "")
    )

    print(f"{run_date}  run_id: {run_id}  status: {status}")

    if sentiment:
        sig_parts = [
            f"{ticker}→{_sentiment_label_to_signal(s.get('label', 'NEUTRAL'))}"
            for ticker, s in sentiment.items()
        ]
        print(f"  Signals:  {' '.join(sig_parts)}")
    elif final_signal:
        print(f"  Signal:   {final_signal}")

    if diff:
        changes = diff.get("signal_changes", [])
        if changes:
            flip_strs = [
                f"{c['ticker']} flipped {c['yesterday']}→{c['today']}"
                for c in changes
            ]
            print(f"  Diff:     {', '.join(flip_strs)}")
        elif not diff.get("baseline"):
            print("  Diff:     No changes vs yesterday")
        else:
            print("  Diff:     Baseline run (no previous day)")

        for drift in diff.get("reasoning_drift", []):
            ticker = drift.get("ticker", "")
            note   = drift.get("note", "")
            print(f'  Drift:    {ticker}: "{note}"')

    print()


def main() -> None:
    """Entry point — parse args and print log summaries."""
    parser = argparse.ArgumentParser(
        description="Review finmat daily briefing logs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/review_logs.py --last 7\n"
            "  python scripts/review_logs.py --date 2026-03-23\n"
            "  python scripts/review_logs.py --flips-only\n"
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="Show the last N calendar days of runs",
    )
    group.add_argument(
        "--date",
        type=str,
        metavar="YYYY-MM-DD",
        help="Show all runs for a specific date",
    )
    parser.add_argument(
        "--flips-only",
        action="store_true",
        help="Only show days where at least one signal changed",
    )
    args = parser.parse_args()

    if not _RUNS_FILE.exists():
        print(f"No runs file found at {_RUNS_FILE}")
        print("Run the daily briefing at least once to generate logs.")
        sys.exit(0)

    diffs_by_run = _load_diffs_by_run_id()
    all_runs     = _collect_runs()

    if not all_runs:
        print(f"No run records found in {_RUNS_FILE}")
        sys.exit(0)

    # ── Filter runs ──
    if args.date:
        filtered = [r for r in all_runs if r.get("date") == args.date]
        title = f"Date {args.date}"
    elif args.last:
        # Collect the last N unique calendar dates (most recent first)
        seen_dates: list[str] = []
        for run in reversed(all_runs):
            d = run.get("date", "")
            if d and d not in seen_dates:
                seen_dates.append(d)
            if len(seen_dates) >= args.last:
                break
        cutoff = set(seen_dates)
        filtered = [r for r in all_runs if r.get("date") in cutoff]
        title = f"Last {args.last} days"
    else:
        filtered = all_runs
        title = "All runs"

    # ── Apply --flips-only ──
    if args.flips_only:
        filtered = [r for r in filtered if _has_flips(r, diffs_by_run)]
        if not filtered:
            print("No runs with signal changes found.")
            sys.exit(0)

    if not filtered:
        print(f"No runs found for: {title}")
        sys.exit(0)

    # Sort most-recent first
    filtered.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

    print(f"\n=== Finmat Log Review — {title} ===\n")

    for run in filtered:
        diff = diffs_by_run.get(run.get("run_id", ""))
        _print_run(run, diff)


if __name__ == "__main__":
    main()
