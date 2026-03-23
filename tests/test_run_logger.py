"""
Tests for modules/run_logger.py.

File I/O is redirected to a tmp_path fixture so tests are fully isolated —
no writes to the real logs/ directory.  The Claude API call in _call_drift_api
is mocked wherever the diff computation would invoke it.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import modules.run_logger as rl_mod
from modules.run_logger import (
    RunLogger,
    _compute_snapshot_diff,
    _find_yesterday_run,
    _iter_runs,
    _sentiment_label_to_signal,
    extract_final_signal,
)


# ── Helpers ────────────────────────────────────────────────────

def _set_log_dir(tmp_path: Path) -> None:
    """Point LOG_DIR at tmp_path for the duration of the test."""
    os.environ["LOG_DIR"] = str(tmp_path)


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


MOCK_SENTIMENT_TODAY = {
    "MSFT": {"label": "BULLISH",  "score": 0.6},
    "AAPL": {"label": "BEARISH",  "score": -0.4},
    "NVDA": {"label": "NEUTRAL",  "score": 0.0},
}
MOCK_SENTIMENT_YESTERDAY = {
    "MSFT": {"label": "NEUTRAL",  "score": 0.0},
    "AAPL": {"label": "BEARISH",  "score": -0.3},
}

MOCK_STEPS_TODAY = {
    "fetch":   {"tickers": ["MSFT", "AAPL"], "data_snapshot": {"MSFT": 420.0, "AAPL": 195.0}},
    "analyse": {
        "prompt_sent":   "PORTFOLIO SNAPSHOT...",
        "raw_response":  "MARKET MOOD: cautious.",
        "parsed_output": {"sentiment": MOCK_SENTIMENT_TODAY},
    },
    "format":  {"prompt_sent": "MARKET MOOD: cautious.", "raw_response": "", "final_signal": "hold"},
}


# ── extract_final_signal ───────────────────────────────────────

class TestExtractFinalSignal:
    def test_defaults_to_hold(self):
        assert extract_final_signal("MARKET MOOD: cautious macro environment.") == "hold"

    def test_detects_sell_keyword(self):
        assert extract_final_signal("You should consider selling NVDA here.") == "sell"

    def test_detects_buy_keyword(self):
        assert extract_final_signal("This is a good entry point to add to position.") == "buy"

    def test_sell_takes_priority_over_hold(self):
        assert extract_final_signal("Recommend selling the position immediately.") == "sell"

    def test_empty_string_returns_hold(self):
        assert extract_final_signal("") == "hold"


# ── _sentiment_label_to_signal ─────────────────────────────────

class TestSentimentLabelToSignal:
    def test_bullish_maps_to_buy(self):
        assert _sentiment_label_to_signal("BULLISH") == "buy"

    def test_slightly_bullish_maps_to_buy(self):
        assert _sentiment_label_to_signal("SLIGHTLY_BULLISH") == "buy"

    def test_bearish_maps_to_sell(self):
        assert _sentiment_label_to_signal("BEARISH") == "sell"

    def test_slightly_bearish_maps_to_sell(self):
        assert _sentiment_label_to_signal("SLIGHTLY_BEARISH") == "sell"

    def test_neutral_maps_to_hold(self):
        assert _sentiment_label_to_signal("NEUTRAL") == "hold"

    def test_unknown_maps_to_hold(self):
        assert _sentiment_label_to_signal("MIXED") == "hold"


# ── _compute_snapshot_diff ─────────────────────────────────────

class TestComputeSnapshotDiff:
    def test_detects_significant_price_change(self):
        result = _compute_snapshot_diff({"MSFT": 400.0}, {"MSFT": 420.0})
        assert "MSFT" in result
        assert abs(result["MSFT"]["price_change_pct"] - 5.0) < 0.01

    def test_ignores_change_below_threshold(self):
        result = _compute_snapshot_diff({"MSFT": 400.0}, {"MSFT": 401.0})
        assert "MSFT" not in result

    def test_ignores_ticker_missing_from_yesterday(self):
        result = _compute_snapshot_diff({}, {"AAPL": 195.0})
        assert result == {}

    def test_skips_non_numeric_values(self):
        result = _compute_snapshot_diff({"MSFT": "n/a"}, {"MSFT": 420.0})
        assert "MSFT" not in result

    def test_skips_zero_yesterday_value(self):
        result = _compute_snapshot_diff({"MSFT": 0}, {"MSFT": 420.0})
        assert "MSFT" not in result


# ── RunLogger — start_run / log_step ──────────────────────────

class TestRunLoggerInit:
    def test_start_run_sets_run_id(self):
        logger = RunLogger()
        logger.start_run(["MSFT"])
        assert logger._run_id != ""

    def test_start_run_sets_date(self):
        logger = RunLogger()
        logger.start_run(["MSFT"])
        assert logger._date != ""

    def test_start_run_initialises_steps(self):
        logger = RunLogger()
        logger.start_run(["MSFT"])
        assert set(logger._steps.keys()) == {"fetch", "analyse", "format"}

    def test_two_runs_have_different_run_ids(self):
        a, b = RunLogger(), RunLogger()
        a.start_run(["MSFT"])
        b.start_run(["MSFT"])
        assert a._run_id != b._run_id

    def test_log_step_merges_data(self):
        logger = RunLogger()
        logger.start_run(["MSFT"])
        logger.log_step("fetch", {"data_snapshot": {"MSFT": 420.0}})
        assert logger._steps["fetch"]["data_snapshot"] == {"MSFT": 420.0}

    def test_log_step_ignores_unknown_step(self):
        logger = RunLogger()
        logger.start_run(["MSFT"])
        logger.log_step("unknown_step", {"foo": "bar"})  # must not raise
        assert "unknown_step" not in logger._steps

    def test_log_step_does_not_raise_on_exception(self):
        logger = RunLogger()
        # _steps is None so update() will fail — must be caught
        logger._steps = None  # type: ignore[assignment]
        logger.log_step("fetch", {"x": 1})  # must not raise


# ── RunLogger — finalise ───────────────────────────────────────

class TestRunLoggerFinalise:
    def test_writes_one_record_to_runs_jsonl(self, tmp_path):
        _set_log_dir(tmp_path)
        with patch.object(rl_mod, "_compute_and_write_diff"):
            logger = RunLogger()
            logger.start_run(["MSFT"])
            logger.log_step("fetch", {"data_snapshot": {"MSFT": 420.0}})
            logger.finalise("success")

        records = _read_jsonl(tmp_path / "runs.jsonl")
        assert len(records) == 1
        assert records[0]["status"] == "success"
        assert records[0]["run_id"] != ""
        assert records[0]["date"] != ""

    def test_two_runs_produce_two_records(self, tmp_path):
        _set_log_dir(tmp_path)
        with patch.object(rl_mod, "_compute_and_write_diff"):
            for _ in range(2):
                logger = RunLogger()
                logger.start_run(["MSFT"])
                logger.finalise("success")

        records = _read_jsonl(tmp_path / "runs.jsonl")
        assert len(records) == 2
        assert records[0]["run_id"] != records[1]["run_id"]

    def test_error_status_stored(self, tmp_path):
        _set_log_dir(tmp_path)
        logger = RunLogger()
        logger.start_run(["MSFT"])
        logger.finalise("error", "Price fetch FAILED")

        records = _read_jsonl(tmp_path / "runs.jsonl")
        assert records[0]["status"] == "error"
        assert records[0]["error"] == "Price fetch FAILED"

    def test_finalise_without_start_run_writes_nothing(self, tmp_path, capsys):
        _set_log_dir(tmp_path)
        logger = RunLogger()
        logger.finalise("success")  # start_run never called

        assert not (tmp_path / "runs.jsonl").exists()
        captured = capsys.readouterr()
        assert "without start_run" in captured.err

    def test_finalise_tolerates_file_io_error(self, tmp_path, capsys):
        _set_log_dir(tmp_path)
        logger = RunLogger()
        logger.start_run(["MSFT"])

        with patch("pathlib.Path.open", side_effect=OSError("disk full")):
            logger.finalise("success")  # must not raise

        captured = capsys.readouterr()
        assert "error" in captured.err.lower()

    def test_diff_triggered_on_success(self, tmp_path):
        _set_log_dir(tmp_path)
        mock_diff = MagicMock()
        with patch.object(rl_mod, "_compute_and_write_diff", mock_diff):
            logger = RunLogger()
            logger.start_run(["MSFT"])
            logger.finalise("success")

        mock_diff.assert_called_once()

    def test_diff_not_triggered_on_error(self, tmp_path):
        _set_log_dir(tmp_path)
        mock_diff = MagicMock()
        with patch.object(rl_mod, "_compute_and_write_diff", mock_diff):
            logger = RunLogger()
            logger.start_run(["MSFT"])
            logger.finalise("error", "boom")

        mock_diff.assert_not_called()


# ── _find_yesterday_run ────────────────────────────────────────

class TestFindYesterdayRun:
    def test_returns_none_when_no_runs_file(self, tmp_path):
        _set_log_dir(tmp_path)
        assert _find_yesterday_run("2026-03-23") is None

    def test_returns_none_when_no_matching_date(self, tmp_path):
        _set_log_dir(tmp_path)
        record = {"run_id": "abc", "date": "2026-03-20", "status": "success", "steps": {}}
        (tmp_path / "runs.jsonl").write_text(json.dumps(record) + "\n")
        assert _find_yesterday_run("2026-03-23") is None

    def test_returns_matching_yesterday_run(self, tmp_path):
        _set_log_dir(tmp_path)
        record = {"run_id": "abc", "date": "2026-03-22", "status": "success", "steps": {}}
        (tmp_path / "runs.jsonl").write_text(json.dumps(record) + "\n")
        result = _find_yesterday_run("2026-03-23")
        assert result is not None
        assert result["run_id"] == "abc"

    def test_ignores_failed_runs(self, tmp_path):
        _set_log_dir(tmp_path)
        record = {"run_id": "abc", "date": "2026-03-22", "status": "error", "steps": {}}
        (tmp_path / "runs.jsonl").write_text(json.dumps(record) + "\n")
        assert _find_yesterday_run("2026-03-23") is None

    def test_returns_last_successful_run_for_date(self, tmp_path):
        _set_log_dir(tmp_path)
        r1 = {"run_id": "first",  "date": "2026-03-22", "status": "success", "steps": {}}
        r2 = {"run_id": "second", "date": "2026-03-22", "status": "success", "steps": {}}
        (tmp_path / "runs.jsonl").write_text(
            json.dumps(r1) + "\n" + json.dumps(r2) + "\n"
        )
        result = _find_yesterday_run("2026-03-23")
        assert result["run_id"] == "second"


# ── _compute_and_write_diff ────────────────────────────────────

class TestComputeAndWriteDiff:
    def test_baseline_when_no_yesterday(self, tmp_path):
        _set_log_dir(tmp_path)
        rl_mod._compute_and_write_diff("run-today", "2026-03-23", MOCK_STEPS_TODAY)

        records = _read_jsonl(tmp_path / "diffs.jsonl")
        assert len(records) == 1
        assert records[0]["baseline"] is True
        assert records[0]["yesterday_run_id"] is None

    def test_detects_signal_flip(self, tmp_path):
        _set_log_dir(tmp_path)
        # Write a yesterday run with different sentiment
        yesterday_steps = {
            "fetch":   {"tickers": ["MSFT"], "data_snapshot": {"MSFT": 410.0}},
            "analyse": {
                "prompt_sent":   "...",
                "raw_response":  "MARKET MOOD: bullish.",
                "parsed_output": {"sentiment": MOCK_SENTIMENT_YESTERDAY},
            },
            "format":  {"prompt_sent": "", "raw_response": "", "final_signal": "hold"},
        }
        yest_record = {
            "run_id": "yest-001",
            "date":   "2026-03-22",
            "status": "success",
            "steps":  yesterday_steps,
        }
        (tmp_path / "runs.jsonl").write_text(json.dumps(yest_record) + "\n")

        with patch.object(rl_mod, "_call_drift_api", return_value="No significant drift."):
            rl_mod._compute_and_write_diff("run-today", "2026-03-23", MOCK_STEPS_TODAY)

        records = _read_jsonl(tmp_path / "diffs.jsonl")
        assert records[0]["baseline"] is False
        # MSFT flipped NEUTRAL→buy
        flips = [c for c in records[0]["signal_changes"] if c.get("flipped")]
        tickers = {c["ticker"] for c in flips}
        assert "MSFT" in tickers

    def test_flags_incomplete_when_today_sentiment_missing_ticker(self, tmp_path):
        _set_log_dir(tmp_path)
        # Yesterday had AAPL; today's sentiment is empty (step failed)
        steps_today_no_sentiment = {
            **MOCK_STEPS_TODAY,
            "analyse": {
                **MOCK_STEPS_TODAY["analyse"],
                "parsed_output": {"sentiment": {}},  # sentiment failed
            },
        }
        yest_record = {
            "run_id": "yest-002",
            "date":   "2026-03-22",
            "status": "success",
            "steps": {
                "fetch":   {"tickers": ["AAPL"], "data_snapshot": {}},
                "analyse": {
                    "raw_response":  "...",
                    "parsed_output": {"sentiment": {"AAPL": {"label": "BULLISH"}}},
                },
                "format": {},
            },
        }
        (tmp_path / "runs.jsonl").write_text(json.dumps(yest_record) + "\n")

        with patch.object(rl_mod, "_call_drift_api", return_value="No significant drift."):
            rl_mod._compute_and_write_diff("run-today", "2026-03-23", steps_today_no_sentiment)

        records = _read_jsonl(tmp_path / "diffs.jsonl")
        incomplete = [c for c in records[0]["signal_changes"] if c.get("comparison_incomplete")]
        assert any(c["ticker"] == "AAPL" for c in incomplete)
        assert "incomplete" in records[0]["summary"]

    def test_write_error_does_not_raise(self, tmp_path, capsys):
        _set_log_dir(tmp_path)
        with patch("pathlib.Path.open", side_effect=OSError("no space")):
            rl_mod._compute_and_write_diff("run-x", "2026-03-23", MOCK_STEPS_TODAY)

        captured = capsys.readouterr()
        assert "error" in captured.err.lower()
