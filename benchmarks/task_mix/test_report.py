"""Regression checks for the independent comparison summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.task_mix.report import (
    aggregate_token_usage,
    common_case_comparison,
    percentile,
    summarize_run,
)


def test_tail_percentiles_use_nearest_rank() -> None:
    assert percentile([1, 2, 3, 4], 0.5) == 2
    assert percentile([1, 2, 3, 4], 0.95) == 4
    assert percentile([], 0.5) is None


def test_only_mutually_successful_cases_compare_call_savings() -> None:
    baseline = [
        {"case_id": "a", "success": True, "luna_calls": 3, "latency_ms": 30},
        {"case_id": "b", "success": False, "luna_calls": 1, "latency_ms": 10},
    ]
    tuned = [
        {"case_id": "a", "success": True, "luna_calls": 1, "latency_ms": 10},
        {"case_id": "b", "success": True, "luna_calls": 4, "latency_ms": 40},
    ]
    comparison = common_case_comparison(baseline, tuned)
    assert comparison["case_ids"] == ["a"]
    assert comparison["baseline_luna_calls"] == 3
    assert comparison["tuned_luna_calls"] == 1


def test_reordered_result_rows_are_rejected(tmp_path: Path) -> None:
    manifest = {"order": ["a", "b"]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "results.jsonl").write_text(json.dumps({"case_id": "b"}) + "\n")
    with pytest.raises(ValueError, match="frozen order prefix"):
        summarize_run(tmp_path)


def test_summary_includes_manifest_policy_and_token_usage(tmp_path: Path) -> None:
    manifest = {
        "order": ["a"],
        "suite": "dev",
        "variant": "optimized",
        "seed": 7,
        "source_sha256": "source",
        "execution_policy": {"difficulty": "large", "max_luna_calls": 30},
    }
    event = {
        "provider": "openai",
        "operation": "reason",
        "input_tokens": 2400,
        "output_tokens": 120,
        "cached_input_tokens": 1024,
        "cache_write_tokens": 0,
        "non_cached_input_tokens": 1376,
        "elapsed_ms": 5,
    }
    row: dict[str, Any] = {
        "case_id": "a",
        "success": True,
        "difficulty": "large",
        "latency_ms": 10,
        "luna_calls": 1,
        "laya_calls": 0,
        "laya_accept_count": 0,
        "actions_completed": 1,
        "provider_events": [event],
        "runtime_status": "completed",
        "evaluation": {"failed_checks": []},
        "errors": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "results.jsonl").write_text(json.dumps(row) + "\n")

    summary, _ = summarize_run(tmp_path)

    assert summary["execution_policy"] == manifest["execution_policy"]
    assert summary["difficulty"]["large"]["cases"] == 1
    assert summary["difficulty"]["large"]["luna_calls"] == 1
    assert summary["difficulty"]["large"]["latency_p50_ms"] == 10
    assert summary["luna_token_usage"] == {
        "events": 1,
        "input_tokens": {
            "total": 2400,
            "reported_total": 2400,
            "reported_events": 1,
            "missing_events": 0,
        },
        "output_tokens": {
            "total": 120,
            "reported_total": 120,
            "reported_events": 1,
            "missing_events": 0,
        },
        "cached_input_tokens": {
            "total": 1024,
            "reported_total": 1024,
            "reported_events": 1,
            "missing_events": 0,
        },
        "cache_write_tokens": {
            "total": 0,
            "reported_total": 0,
            "reported_events": 1,
            "missing_events": 0,
        },
        "non_cached_input_tokens": {
            "total": 1376,
            "reported_total": 1376,
            "reported_events": 1,
            "missing_events": 0,
        },
    }


def test_token_usage_marks_partial_and_absent_counts_unknown() -> None:
    usage = aggregate_token_usage(
        [
            {"input_tokens": 100, "cache_write_tokens": 0},
            {"input_tokens": None, "cached_input_tokens": 20},
        ]
    )

    assert usage["input_tokens"] == {
        "total": None,
        "reported_total": 100,
        "reported_events": 1,
        "missing_events": 1,
    }
    assert usage["cache_write_tokens"] == {
        "total": None,
        "reported_total": 0,
        "reported_events": 1,
        "missing_events": 1,
    }
    assert usage["cached_input_tokens"] == {
        "total": None,
        "reported_total": 20,
        "reported_events": 1,
        "missing_events": 1,
    }
    assert usage["output_tokens"]["total"] is None
    assert usage["output_tokens"]["reported_total"] == 0
    assert usage["output_tokens"]["reported_events"] == 0
    assert usage["output_tokens"]["missing_events"] == 2
