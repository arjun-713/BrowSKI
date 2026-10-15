"""Summarize frozen task runs without replacing their independent gold checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any


def percentile(samples: list[float], fraction: float) -> float | None:
    """Use nearest rank; with this small corpus, tail percentiles are maxima."""
    if not samples:
        return None
    ordered = sorted(samples)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return round(ordered[min(rank, len(ordered)) - 1], 2)


def aggregate_token_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate reported Luna usage without treating absent fields as zero."""
    fields = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cached_input_tokens": "cached_input_tokens",
        "cache_write_tokens": "cache_write_tokens",
        "non_cached_input_tokens": "non_cached_input_tokens",
    }
    usage: dict[str, Any] = {"events": len(events)}
    for name, event_key in fields.items():
        reported = [
            event[event_key]
            for event in events
            if isinstance(event.get(event_key), int)
            and not isinstance(event.get(event_key), bool)
        ]
        missing = len(events) - len(reported)
        usage[name] = {
            # The total is only complete when every relevant event reported it.
            "total": sum(reported) if events and not missing else None,
            "reported_total": sum(reported),
            "reported_events": len(reported),
            "missing_events": missing,
        }
    return usage


def summarize_run(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = json.loads((directory / "manifest.json").read_text())
    results_path = directory / "results.jsonl"
    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    expected_order = manifest["order"]
    recorded_order = [row["case_id"] for row in rows]
    if recorded_order != expected_order[: len(rows)]:
        raise ValueError(f"results are not the frozen order prefix: {directory}")
    if len(recorded_order) > len(expected_order):
        raise ValueError(f"run contains extra cases: {directory}")
    successes = sum(bool(row["success"]) for row in rows)
    successful = [row for row in rows if row["success"]]
    provider_events = [event for row in rows for event in row["provider_events"]]
    luna_events = [
        event
        for event in provider_events
        if event["provider"] == "openai" and event["operation"] in {"reason", "vision"}
    ]
    latencies = [float(row["latency_ms"]) for row in rows]
    successful_latencies = [float(row["latency_ms"]) for row in successful]
    breakdown = {}
    for difficulty in ("small", "medium", "large"):
        group = [row for row in rows if row["difficulty"] == difficulty]
        breakdown[difficulty] = {
            "cases": len(group),
            "successes": sum(bool(row["success"]) for row in group),
            "luna_calls": sum(row["luna_calls"] for row in group),
            "latency_p50_ms": percentile(
                [float(row["latency_ms"]) for row in group], 0.5
            ),
        }
    summary = {
        "directory": str(directory),
        "suite": manifest["suite"],
        "variant": manifest["variant"],
        "execution_policy": manifest.get("execution_policy"),
        "expected_cases": len(expected_order),
        "recorded_cases": len(rows),
        "complete": recorded_order == expected_order,
        "successes": successes,
        "success_rate": successes / len(rows) if rows else None,
        "luna_calls": sum(row["luna_calls"] for row in rows),
        "laya_calls": sum(row["laya_calls"] for row in rows),
        "laya_accepted": sum(row["laya_accept_count"] for row in rows),
        "actions_completed_events": sum(row["actions_completed"] for row in rows),
        "luna_calls_successful_cases": sum(row["luna_calls"] for row in successful),
        "mean_luna_calls_successful_case": (
            sum(row["luna_calls"] for row in successful) / len(successful)
            if successful
            else None
        ),
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "p99": percentile(latencies, 0.99),
        },
        "successful_case_latency_ms": {
            "p50": percentile(successful_latencies, 0.5),
            "p95": percentile(successful_latencies, 0.95),
            "p99": percentile(successful_latencies, 0.99),
        },
        "luna_latency_ms": {
            "p50": percentile([float(e["elapsed_ms"]) for e in luna_events], 0.5),
            "p95": percentile([float(e["elapsed_ms"]) for e in luna_events], 0.95),
            "p99": percentile([float(e["elapsed_ms"]) for e in luna_events], 0.99),
        },
        "luna_token_usage": aggregate_token_usage(luna_events),
        "provider_errors": dict(
            Counter(e["error_type"] for e in provider_events if e.get("error_type"))
        ),
        "runtime_statuses": dict(Counter(row["runtime_status"] for row in rows)),
        "difficulty": breakdown,
        "unexecuted_cases": expected_order[len(rows) :],
        "seed": manifest["seed"],
        "source_sha256": manifest["source_sha256"],
        "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        "failed_cases": [
            {
                "case_id": row["case_id"],
                "checks": row["evaluation"]["failed_checks"],
                "runtime_status": row["runtime_status"],
                "errors": row["errors"],
            }
            for row in rows
            if not row["success"]
        ],
    }
    return summary, rows


def common_case_comparison(
    baseline: list[dict[str, Any]], tuned: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare only cases that both variants completed successfully."""
    old = {row["case_id"]: row for row in baseline if row["success"]}
    new = {row["case_id"]: row for row in tuned if row["success"]}
    common = sorted(old.keys() & new.keys())
    return {
        "case_ids": common,
        "baseline_luna_calls": sum(old[key]["luna_calls"] for key in common),
        "tuned_luna_calls": sum(new[key]["luna_calls"] for key in common),
        "baseline_latency_median_ms": (
            median(old[key]["latency_ms"] for key in common) if common else None
        ),
        "tuned_latency_median_ms": (
            median(new[key]["latency_ms"] for key in common) if common else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tuned", type=Path, required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summaries: dict[str, dict[str, Any]] = {}
    records: dict[str, list[dict[str, Any]]] = {}
    for label in ("baseline", "tuned", "holdout"):
        summaries[label], records[label] = summarize_run(getattr(args, label))
    report = {
        "metric_version": 1,
        "percentile_method": "nearest_rank",
        "primary_ground_truth": "frozen independent browser-state checks",
        "runs": summaries,
        "common_successful_cases": common_case_comparison(
            records["baseline"], records["tuned"]
        ),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "comparison.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    columns = [
        "variant",
        "case_id",
        "difficulty",
        "success",
        "runtime_status",
        "luna_calls",
        "laya_calls",
        "latency_ms",
        "failed_checks",
    ]
    with (args.output / "comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for label, rows in records.items():
            for row in rows:
                writer.writerow(
                    {
                        **{key: row[key] for key in columns[:-1]},
                        "variant": label,
                        "failed_checks": ";".join(row["evaluation"]["failed_checks"]),
                    }
                )
    print(args.output / "comparison.json")


if __name__ == "__main__":
    main()
