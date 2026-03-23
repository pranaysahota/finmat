"""JSONL run logger for the daily briefing workflow.

Records every run as a self-contained JSON line in logs/runs.jsonl.
After a successful run, automatically computes a diff vs. yesterday and
appends it to logs/diffs.jsonl.

All file I/O is wrapped in try/except — a logging failure never crashes
the main workflow. Errors are emitted to sys.stderr only.

Structured records are also printed to stdout (Option B) so they can be
inspected via `fly logs -a finmat | grep RUN_LOG` without SSH access.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


_WORKFLOW_VERSION = "1.0.0"


def _log_dir() -> Path:
    """Return the log directory path, resolved from LOG_DIR env var."""
    return Path(os.environ.get("LOG_DIR", "logs"))


def _runs_path() -> Path:
    return _log_dir() / "runs.jsonl"


def _diffs_path() -> Path:
    return _log_dir() / "diffs.jsonl"


def _iter_runs() -> Iterator[dict]:
    """Yield run records one at a time from runs.jsonl — never loads whole file."""
    path = _runs_path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def _find_yesterday_run(today_date: str) -> dict | None:
    """Return the most recent successful run from yesterday, or None.

    Args:
        today_date: ISO date string (YYYY-MM-DD) for today.

    Returns:
        The last successful run record for yesterday, or None if not found.
    """
    yesterday = (
        datetime.fromisoformat(today_date) - timedelta(days=1)
    ).date().isoformat()
    found: dict | None = None
    for run in _iter_runs():
        if run.get("date") == yesterday and run.get("status") == "success":
            found = run  # keep the last one for that date
    return found


def extract_final_signal(decision_text: str) -> str:
    """Infer a buy / sell / hold signal from the decision engine's free-text output.

    Uses simple keyword matching against the decision text. Defaults to "hold"
    since the system is configured to be in a HOLD phase.

    Args:
        decision_text: Raw text returned by the decision engine.

    Returns:
        One of "buy", "sell", or "hold".
    """
    text_lower = decision_text.lower()
    sell_keywords = ["consider selling", "recommend selling", "crystallise", "take profit"]
    buy_keywords  = ["consider buying", "good entry", "add to position", "accumulate"]
    if any(kw in text_lower for kw in sell_keywords):
        return "sell"
    if any(kw in text_lower for kw in buy_keywords):
        return "buy"
    return "hold"


def _sentiment_label_to_signal(label: str) -> str:
    """Map a sentiment label string to a buy/sell/hold signal.

    Args:
        label: Sentiment label such as "BULLISH", "BEARISH", "NEUTRAL".

    Returns:
        "buy", "sell", or "hold".
    """
    upper = label.upper()
    if "BEARISH" in upper:
        return "sell"
    if "BULLISH" in upper:
        return "buy"
    return "hold"


def _call_drift_api(yesterday_response: str, today_response: str) -> str:
    """Call Claude Haiku to summarise reasoning drift between two daily outputs.

    Returns a single sentence describing what shifted between the two days,
    or "No significant drift." if nothing meaningful changed.

    Args:
        yesterday_response: Full raw analysis text from yesterday's run.
        today_response:     Full raw analysis text from today's run.

    Returns:
        One-sentence drift summary, or a fallback string on error.
    """
    try:
        import anthropic  # noqa: PLC0415 — conditional import, not in requirements scope

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return "Drift analysis skipped — ANTHROPIC_API_KEY not set."

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are comparing two financial analysis outputs for the same portfolio "
            "on consecutive days.\n\n"
            f"Yesterday's reasoning:\n{yesterday_response}\n\n"
            f"Today's reasoning:\n{today_response}\n\n"
            "In one sentence, describe the key shift in reasoning between the two days. "
            "Be specific about what changed — data, sentiment, or framing. "
            'If there is no meaningful change, say "No significant drift."'
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    except Exception as exc:
        print(f"_call_drift_api error: {exc}", file=sys.stderr)
        return "Drift analysis unavailable."


def _compute_snapshot_diff(
    yesterday_snapshot: dict,
    today_snapshot: dict,
) -> dict:
    """Compare two price snapshot dicts and return per-ticker diffs.

    Only includes tickers where the numeric value changed by more than 0.5%.

    Args:
        yesterday_snapshot: Dict of {ticker: price} from yesterday.
        today_snapshot:     Dict of {ticker: price} from today.

    Returns:
        Dict of {ticker: {"price_change_pct": float, "fields_changed": list}}.
    """
    result: dict = {}
    for ticker, today_val in today_snapshot.items():
        if ticker not in yesterday_snapshot:
            continue
        yest_val = yesterday_snapshot[ticker]
        if not isinstance(today_val, (int, float)):
            continue
        if not isinstance(yest_val, (int, float)):
            continue
        if yest_val == 0:
            continue
        pct_change = ((today_val - yest_val) / abs(yest_val)) * 100
        if abs(pct_change) > 0.5:
            result[ticker] = {
                "price_change_pct": round(pct_change, 2),
                "fields_changed":   ["price"],
            }
    return result


def _compute_and_write_diff(run_id: str, run_date: str, steps: dict) -> None:
    """Compute a diff record vs. yesterday's run and append it to diffs.jsonl.

    Also emits the diff record to stdout for fly.io log streaming.

    Args:
        run_id:   UUID of today's completed run.
        run_date: ISO date string (YYYY-MM-DD) for today.
        steps:    The completed steps dict from today's run.
    """
    yesterday_run = _find_yesterday_run(run_date)
    diff_id = str(uuid.uuid4())
    now_ts  = datetime.now(timezone.utc).isoformat()

    if yesterday_run is None:
        diff_record: dict = {
            "diff_id":            diff_id,
            "timestamp":          now_ts,
            "today_run_id":       run_id,
            "yesterday_run_id":   None,
            "baseline":           True,
            "signal_changes":     [],
            "reasoning_drift":    [],
            "data_snapshot_diff": {},
            "summary":            "Baseline run — no previous day to compare.",
        }
    else:
        # ── Signal changes (per-ticker sentiment labels as proxy signals) ──
        today_sentiment: dict = (
            steps.get("analyse", {}).get("parsed_output", {}).get("sentiment", {})
        )
        yesterday_sentiment: dict = (
            yesterday_run.get("steps", {})
            .get("analyse", {})
            .get("parsed_output", {})
            .get("sentiment", {})
        )

        signal_changes: list[dict] = []
        for ticker, today_s in today_sentiment.items():
            if ticker not in yesterday_sentiment:
                continue
            today_sig = _sentiment_label_to_signal(today_s.get("label", "NEUTRAL"))
            yest_sig  = _sentiment_label_to_signal(
                yesterday_sentiment[ticker].get("label", "NEUTRAL")
            )
            if today_sig != yest_sig:
                signal_changes.append({
                    "ticker":    ticker,
                    "yesterday": yest_sig,
                    "today":     today_sig,
                    "flipped":   True,
                })

        # ── Reasoning drift (portfolio-level Claude Haiku call) ──
        today_response     = steps.get("analyse", {}).get("raw_response", "")
        yesterday_response = (
            yesterday_run.get("steps", {}).get("analyse", {}).get("raw_response", "")
        )

        reasoning_drift: list[dict] = []
        if today_response and yesterday_response:
            note = _call_drift_api(yesterday_response, today_response)
            if note and "No significant drift" not in note:
                reasoning_drift.append({"ticker": "PORTFOLIO", "note": note})

        # ── Data snapshot diff (price-level comparison) ──
        today_snapshot     = steps.get("fetch", {}).get("data_snapshot", {})
        yesterday_snapshot = (
            yesterday_run.get("steps", {}).get("fetch", {}).get("data_snapshot", {})
        )
        snap_diff = _compute_snapshot_diff(yesterday_snapshot, today_snapshot)

        # ── Summary string ──
        flipped_count = len(signal_changes)
        if flipped_count == 0:
            summary = "No signal changes vs yesterday."
        else:
            examples = ", ".join(
                f"{c['ticker']} {c['yesterday']}→{c['today']}"
                for c in signal_changes[:3]
            )
            summary = f"{flipped_count} signal(s) changed since yesterday. {examples}."

        diff_record = {
            "diff_id":            diff_id,
            "timestamp":          now_ts,
            "today_run_id":       run_id,
            "yesterday_run_id":   yesterday_run.get("run_id"),
            "baseline":           False,
            "signal_changes":     signal_changes,
            "reasoning_drift":    reasoning_drift,
            "data_snapshot_diff": snap_diff,
            "summary":            summary,
            "metadata":           {"diff_model": "claude-haiku-4-5-20251001"},
        }

    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        with _diffs_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(diff_record, default=str) + "\n")
        print(json.dumps({"level": "DIFF_LOG", **diff_record}, default=str), flush=True)
    except Exception as exc:
        print(f"_compute_and_write_diff write error: {exc}", file=sys.stderr)


class RunLogger:
    """Records a single daily briefing workflow run as a JSONL line.

    Usage:
        logger = RunLogger()
        logger.start_run(tickers)
        logger.log_step("fetch",   {"tickers": [...], "data_snapshot": {...}})
        logger.log_step("analyse", {"prompt_sent": "...", "raw_response": "...", ...})
        logger.log_step("format",  {"prompt_sent": "...", "final_signal": "hold"})
        logger.finalise("success")

    All methods are safe to call even if start_run() was never called — any
    exception is swallowed and printed to stderr so the main pipeline continues.
    """

    def __init__(self) -> None:
        self._run_id:    str  = ""
        self._timestamp: str  = ""
        self._date:      str  = ""
        self._steps:     dict = {}
        self._metadata:  dict = {}

    def start_run(self, tickers: list[str]) -> None:
        """Initialise a new run record with a fresh UUID and empty step containers.

        Args:
            tickers: All ticker symbols that will be processed in this run.
        """
        try:
            now = datetime.now(timezone.utc)
            self._run_id    = str(uuid.uuid4())
            self._timestamp = now.isoformat()
            self._date      = now.date().isoformat()
            self._steps = {
                "fetch":   {"tickers": tickers, "data_snapshot": {}},
                "analyse": {"prompt_sent": "", "raw_response": "", "parsed_output": {}},
                "format":  {"prompt_sent": "", "raw_response": "", "final_signal": "hold"},
            }
            self._metadata = {
                "model":            "claude-sonnet-4-6",
                "temperature":       1.0,
                "workflow_version":  _WORKFLOW_VERSION,
            }
        except Exception as exc:
            print(f"RunLogger.start_run error: {exc}", file=sys.stderr)

    def log_step(self, step_name: str, data: dict) -> None:
        """Merge data into the named step of the current run.

        Args:
            step_name: One of "fetch", "analyse", "format".
            data:      Fields to merge into the step's existing dict.
        """
        try:
            if step_name in self._steps:
                self._steps[step_name].update(data)
        except Exception as exc:
            print(f"RunLogger.log_step({step_name!r}) error: {exc}", file=sys.stderr)

    def finalise(self, status: str, error: str | None = None) -> None:
        """Serialise the run record and append it to logs/runs.jsonl.

        Emits the record to stdout for fly.io log streaming.
        Triggers the daily diff computation when status is "success".

        Args:
            status: "success" or "error".
            error:  Error message string, or None when status is "success".
        """
        try:
            record: dict = {
                "run_id":    self._run_id,
                "timestamp": self._timestamp,
                "date":      self._date,
                "steps":     self._steps,
                "metadata":  self._metadata,
                "status":    status,
                "error":     error,
            }
            log_dir = _log_dir()
            log_dir.mkdir(parents=True, exist_ok=True)
            with _runs_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
            print(json.dumps({"level": "RUN_LOG", **record}, default=str), flush=True)
        except Exception as exc:
            print(f"RunLogger.finalise write error: {exc}", file=sys.stderr)
            return

        if status == "success":
            try:
                _compute_and_write_diff(self._run_id, self._date, self._steps)
            except Exception as exc:
                print(f"RunLogger.finalise diff error: {exc}", file=sys.stderr)
