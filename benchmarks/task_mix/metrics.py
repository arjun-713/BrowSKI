"""Direct event tallies for task-mix runs."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmarks.task_mix.dataset import source_checksum


def build_manifest(
    cases: Sequence[Any],
    suite: str,
    variant: str,
    seed: int,
    base_url: str,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Freeze corpus, benchmark-code, and runtime-source identities pre-run."""
    order = [case.case_id for case in cases]
    if suite == "holdout":
        data_path = Path(__file__).resolve().parent / "holdout.jsonl"
        source_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    else:
        source_hash = source_checksum(include_holdout=suite == "all")
    order_hash = hashlib.sha256(
        json.dumps(order, separators=(",", ":")).encode()
    ).hexdigest()
    runtime_root = source_root.resolve() if source_root else None
    if runtime_root and runtime_root.name == "browser_agent":
        runtime_root = runtime_root.parent
    if runtime_root is None:
        runtime_root = Path(__file__).resolve().parents[2] / "python" / "src"
    runtime_package = runtime_root / "browser_agent"
    runtime_manifest = runtime_root / "manifest.json" if runtime_root else None
    runtime_module_names = (
        "agent/runtime.py",
        "agent/luna.py",
        "agent/graph.py",
        "decisions/laya.py",
        "reasoning/openai_adapter.py",
        "session.py",
    )
    module_paths = {
        name: Path(__file__).resolve().parent / name
        for name in (
            "runner.py",
            "evaluate.py",
            "metrics.py",
            "budgets.py",
            "dataset.py",
            "schema.py",
            "resume.py",
        )
    }

    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "benchmark": "browski-task-mix-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "suite": suite,
        "variant": variant,
        "seed": seed,
        "source_sha256": source_hash,
        "benchmark_module_sha256": {
            name: sha256(path) for name, path in module_paths.items()
        },
        "runtime_module_sha256": {
            name: sha256(runtime_package / name)
            for name in runtime_module_names
            if (runtime_package / name).is_file()
        },
        "frozen_runtime_manifest_sha256": (
            sha256(runtime_manifest)
            if runtime_manifest is not None and runtime_manifest.is_file()
            else None
        ),
        "frozen_runtime_git_commit": (
            json.loads(runtime_manifest.read_text(encoding="utf-8")).get("git_commit")
            if runtime_manifest is not None and runtime_manifest.is_file()
            else None
        ),
        "order_sha256": order_hash,
        "order": order,
        "start_urls": {
            case.case_id: f"{base_url}{case.start_path}?benchmark_case={case.case_id}"
            for case in cases
        },
        "source_root": str(runtime_root) if runtime_root else None,
        "bounds": {"max_case_seconds": 120},
    }


class EventTally:
    """Count every provider telemetry callback, including repeated events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.by_provider_operation: Counter[str] = Counter()
        self.by_provider_outcome: Counter[str] = Counter()
        self.tokens: Counter[str] = Counter()
        self.input_tokens: Counter[str] = Counter()
        self.output_tokens: Counter[str] = Counter()

    def __call__(self, event: Any) -> None:
        row = asdict(event) if is_dataclass(event) else dict(vars(event))
        provider = str(row.get("provider", "unknown"))
        operation = str(row.get("operation", "unknown"))
        outcome = str(row.get("outcome", "unknown"))
        self.by_provider_operation[f"{provider}:{operation}"] += 1
        self.by_provider_outcome[f"{provider}:{outcome}"] += 1
        input_tokens = int(row.get("input_tokens") or 0)
        output_tokens = int(row.get("output_tokens") or 0)
        self.input_tokens[provider] += input_tokens
        self.output_tokens[provider] += output_tokens
        self.tokens[provider] += input_tokens + output_tokens
        # Preserve one row per callback. Never collapse on run/step/call IDs.
        self.events.append(row)

    def summary(self) -> dict[str, Any]:
        return {
            "provider_operation_events": dict(
                sorted(self.by_provider_operation.items())
            ),
            "provider_outcome_events": dict(sorted(self.by_provider_outcome.items())),
            "token_totals": dict(sorted(self.tokens.items())),
            "input_tokens": dict(sorted(self.input_tokens.items())),
            "output_tokens": dict(sorted(self.output_tokens.items())),
            "provider_event_count": len(self.events),
        }


class RuntimeTally:
    """Count the Rust-backed runtime's content-minimal lifecycle events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: Any) -> None:
        kind = getattr(event.type, "value", str(event.type))
        self.events.append(
            {
                "type": kind,
                "status": event.status,
                "step": event.step,
                "sequence": event.sequence,
            }
        )

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(str(row["type"]) for row in self.events).items()))

    def count(self, name: str) -> int:
        return sum(row["type"] == name for row in self.events)
