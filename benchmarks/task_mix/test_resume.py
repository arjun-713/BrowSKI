"""Tests for safe continuation of interrupted task-mix runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.task_mix.resume import reconstruct_aggregate, validate_resume


def _manifest() -> dict[str, Any]:
    order = ["case-1", "case-2", "case-3"]
    order_hash = hashlib.sha256(
        json.dumps(order, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "benchmark": "browski-task-mix-v1",
        "suite": "dev",
        "variant": "optimized",
        "seed": 9,
        "order": order,
        "order_sha256": order_hash,
        "source_sha256": "dataset-hash",
        "runtime_module_sha256": {"agent/runtime.py": "runtime-hash"},
        "frozen_runtime_manifest_sha256": "runtime-manifest-hash",
        "frozen_runtime_git_commit": "frozen-commit",
        "start_urls": {"case-1": "http://127.0.0.1:1000/one"},
    }


def _record(case_id: str, order: int) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "order": order,
        "variant": "optimized",
        "run_id": "run-123",
        "success": True,
        "evaluation": {"failed_checks": []},
        "provider_metrics": {
            "provider_operation_events": {"openai:reason": 2},
            "provider_outcome_events": {"openai:success": 2},
        },
        "runtime_event_counts": {"ActionCompleted": 1},
        "provider_debug_records": 2,
    }


def _prepare_run(
    directory: Path,
    records: list[dict[str, Any]] | None = None,
) -> Path:
    directory.mkdir()
    (directory / "debug").mkdir()
    (directory / "provider-debug.jsonl").write_text("", encoding="utf-8")
    (directory / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
    (directory / "results.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in records or []),
        encoding="utf-8",
    )
    return directory


def test_validate_resume_accepts_a_frozen_order_prefix(tmp_path: Path) -> None:
    run_directory = _prepare_run(
        tmp_path / "run-123",
        [_record("case-1", 0), _record("case-2", 1)],
    )

    state = validate_resume(run_directory, _manifest())

    assert state.run_id == "run-123"
    assert state.next_order == 2
    assert [row["case_id"] for row in state.records] == ["case-1", "case-2"]


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([_record("case-1", 0), _record("case-1", 1)], "duplicate"),
        ([_record("case-2", 0)], "frozen-order prefix"),
        ([_record("case-1", 1)], "order is invalid"),
    ],
)
def test_validate_resume_rejects_invalid_prefixes(
    tmp_path: Path,
    records: list[dict[str, Any]],
    message: str,
) -> None:
    run_directory = _prepare_run(tmp_path / "run-123", records)

    with pytest.raises(ValueError, match=message):
        validate_resume(run_directory, _manifest())


@pytest.mark.parametrize(
    "field",
    [
        "suite",
        "variant",
        "seed",
        "order",
        "source_sha256",
        "runtime_module_sha256",
        "frozen_runtime_manifest_sha256",
    ],
)
def test_validate_resume_rejects_manifest_mismatches(
    tmp_path: Path,
    field: str,
) -> None:
    run_directory = _prepare_run(tmp_path / "run-123", [_record("case-1", 0)])
    requested_manifest = _manifest()
    requested_manifest[field] = "different"

    with pytest.raises(ValueError, match="manifest mismatch"):
        validate_resume(run_directory, requested_manifest)


@pytest.mark.parametrize("summary_name", ["summary.json", "summary.csv"])
def test_validate_resume_rejects_completed_summary(
    tmp_path: Path,
    summary_name: str,
) -> None:
    run_directory = _prepare_run(tmp_path / "run-123", [_record("case-1", 0)])
    (run_directory / summary_name).write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="completed run"):
        validate_resume(run_directory, _manifest())


def test_reconstruct_aggregate_includes_preserved_prefix_records() -> None:
    records = [_record("case-1", 0), _record("case-2", 1)]

    summary = reconstruct_aggregate(
        "run-123",
        "dev",
        "optimized",
        records,
        total_cases=3,
    )

    assert summary["successes"] == 2
    assert summary["success_rate"] == pytest.approx(2 / 3)
    assert summary["provider_operation_events"] == {"openai:reason": 4}
    assert summary["runtime_event_counts"] == {"ActionCompleted": 2}
    assert [row["case_id"] for row in summary["case_results"]] == [
        "case-1",
        "case-2",
    ]
