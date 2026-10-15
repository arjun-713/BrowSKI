"""Validation and reconstruction helpers for interrupted task-mix runs."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ResumeState:
    """Existing run data that can be safely continued."""

    run_id: str
    records: list[dict[str, Any]]
    next_order: int


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read resume metadata {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"resume metadata must be a JSON object: {path}")
    return value


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read resume results {path}: {exc}") from exc

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid result at {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise TypeError(f"result at {path}:{line_number} must be an object")
        records.append(record)
    return records


def validate_resume(
    run_directory: Path,
    requested_manifest: dict[str, Any],
) -> ResumeState:
    """Validate run identity and require results to be an ordered suite prefix."""
    run_directory = run_directory.expanduser().resolve()
    if not run_directory.is_dir():
        raise ValueError(f"resume directory does not exist: {run_directory}")

    for completed_name in ("summary.json", "summary.csv"):
        if (run_directory / completed_name).exists():
            raise ValueError(
                f"cannot resume completed run with {completed_name}: {run_directory}"
            )

    initial_manifest = _read_json(run_directory / "manifest.json")
    identity_fields = (
        "benchmark",
        "suite",
        "variant",
        "seed",
        "order",
        "order_sha256",
        "source_sha256",
        "runtime_module_sha256",
        "frozen_runtime_manifest_sha256",
        "frozen_runtime_git_commit",
        "execution_policy",
        "bounds",
    )
    for field in identity_fields:
        if initial_manifest.get(field) != requested_manifest.get(field):
            raise ValueError(f"resume manifest mismatch for {field}")

    expected_order = requested_manifest.get("order")
    if not isinstance(expected_order, list) or not expected_order:
        raise ValueError("requested manifest has no frozen case order")
    expected_order_hash = hashlib.sha256(
        json.dumps(expected_order, separators=(",", ":")).encode()
    ).hexdigest()
    if requested_manifest.get("order_sha256") != expected_order_hash:
        raise ValueError("requested manifest case order hash is invalid")

    results_path = run_directory / "results.jsonl"
    if not results_path.is_file():
        raise ValueError(f"resume results file does not exist: {results_path}")
    records = _read_records(results_path)
    if len(records) >= len(expected_order):
        raise ValueError("cannot resume a run with a complete case result set")

    run_ids: set[str] = set()
    seen_case_ids: set[str] = set()
    for order, record in enumerate(records):
        expected_case_id = expected_order[order]
        case_id = record.get("case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate completed case result: {case_id}")
        if case_id != expected_case_id:
            raise ValueError(
                "existing results are not a frozen-order prefix: "
                f"order {order} is {case_id!r}, expected {expected_case_id!r}"
            )
        if record.get("order") != order:
            raise ValueError(f"existing result order is invalid for {case_id}")
        if record.get("variant") != requested_manifest.get("variant"):
            raise ValueError(f"existing result variant is invalid for {case_id}")
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"existing result has no run_id for {case_id}")
        run_ids.add(run_id)
        seen_case_ids.add(case_id)

    if len(run_ids) > 1:
        raise ValueError("existing results contain multiple run IDs")
    if not run_ids:
        raise ValueError("cannot resume a run with no completed result prefix")
    if run_directory.name != next(iter(run_ids)):
        raise ValueError("resume directory name does not match the recorded run ID")

    if not (run_directory / "debug").is_dir():
        raise ValueError(f"resume debug directory does not exist: {run_directory}")
    if not (run_directory / "provider-debug.jsonl").is_file():
        raise ValueError(f"resume provider debug log does not exist: {run_directory}")

    return ResumeState(
        run_id=next(iter(run_ids)),
        records=records,
        next_order=len(records),
    )


def reconstruct_aggregate(
    run_id: str,
    suite: str,
    variant: str,
    records: list[dict[str, Any]],
    total_cases: int,
) -> dict[str, Any]:
    """Rebuild the run summary from original and newly appended case records."""
    provider_operations: dict[str, int] = {}
    provider_outcomes: dict[str, int] = {}
    runtime_counts: dict[str, int] = {}
    provider_debug_records = 0
    case_results: list[dict[str, Any]] = []
    successes = 0

    for record in records:
        successes += int(bool(record.get("success")))
        metrics = record.get("provider_metrics") or {}
        for key, count in (metrics.get("provider_operation_events") or {}).items():
            provider_operations[key] = provider_operations.get(key, 0) + int(count)
        for key, count in (metrics.get("provider_outcome_events") or {}).items():
            provider_outcomes[key] = provider_outcomes.get(key, 0) + int(count)
        for key, count in (record.get("runtime_event_counts") or {}).items():
            runtime_counts[key] = runtime_counts.get(key, 0) + int(count)
        provider_debug_records += int(record.get("provider_debug_records", 0))
        case_results.append(
            {
                "case_id": record["case_id"],
                "success": bool(record.get("success")),
                "failed_checks": record.get("evaluation", {}).get("failed_checks", []),
            }
        )

    return {
        "run_id": run_id,
        "suite": suite,
        "variant": variant,
        "cases": total_cases,
        "successes": successes,
        "provider_operation_events": dict(sorted(provider_operations.items())),
        "provider_outcome_events": dict(sorted(provider_outcomes.items())),
        "runtime_event_counts": dict(sorted(runtime_counts.items())),
        "provider_debug_records": provider_debug_records,
        "case_results": case_results,
        "success_rate": successes / total_cases if total_cases else 0.0,
    }


def append_resume_manifest(
    run_directory: Path,
    initial_manifest: dict[str, Any],
    current_manifest: dict[str, Any],
    start_order: int,
) -> None:
    """Record new fixture origin and continuation details without rewriting provenance."""
    initial_urls = initial_manifest.get("start_urls", {}).values()
    initial_origin = next(
        (
            "/".join(url.split("/", 3)[:3])
            for url in initial_urls
            if isinstance(url, str)
        ),
        None,
    )
    current_urls = current_manifest.get("start_urls", {}).values()
    current_origin = next(
        (
            "/".join(url.split("/", 3)[:3])
            for url in current_urls
            if isinstance(url, str)
        ),
        None,
    )
    entry = {
        "resumed_at": current_manifest.get("created_at"),
        "previous_origin": initial_origin,
        "new_origin": current_origin,
        "started_at_order": start_order,
        "runtime_module_sha256": current_manifest.get("runtime_module_sha256"),
        "frozen_runtime_manifest_sha256": current_manifest.get(
            "frozen_runtime_manifest_sha256"
        ),
    }
    path = run_directory / "resume-manifest.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
