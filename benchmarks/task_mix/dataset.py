"""Load and deterministically shuffle the frozen local browser task mix."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from benchmarks.task_mix.schema import TaskCase

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_SEED = 20261012
EXPECTED_COUNTS = {
    "development": {"small": 6, "medium": 6, "large": 6},
    "holdout": {"small": 3, "medium": 3, "large": 3},
}


def load_cases(split: str = "development") -> tuple[TaskCase, ...]:
    """Read a split, validating IDs, intended-action bands, and suite shape."""
    if split not in EXPECTED_COUNTS:
        raise ValueError("split must be 'development' or 'holdout'")
    path = DATA_DIR / f"{split}.jsonl"
    cases = load_case_file(path)
    actual = {
        difficulty: sum(case.difficulty == difficulty for case in cases)
        for difficulty in ("small", "medium", "large")
    }
    if actual != EXPECTED_COUNTS[split]:
        raise ValueError(f"unexpected {split} difficulty counts: {actual}")
    return cases


def load_case_file(path: Path) -> tuple[TaskCase, ...]:
    """Read an explicitly frozen corpus without modifying the V1 suite shape."""
    if path.stat().st_size > 3 * 1024 * 1024:
        raise ValueError("task corpus exceeds the 3 MiB safety bound")
    cases: list[TaskCase] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if line.strip():
                try:
                    cases.append(TaskCase.from_mapping(json.loads(line)))
                except Exception as exc:
                    raise ValueError(
                        f"invalid case at {path}:{line_number}: {exc}"
                    ) from exc
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate case IDs in {path.name}")
    if not cases or len(cases) > 100:
        raise ValueError("an explicit task corpus must contain 1–100 cases")
    return tuple(cases)


def shuffled_suite(
    base_url: str,
    *,
    include_holdout: bool = False,
    seed: int = DEFAULT_SEED,
) -> tuple[dict[str, Any], ...]:
    """Return a repeatable order and substitute local URLs after shuffling."""
    cases = list(load_cases("development"))
    if include_holdout:
        cases.extend(load_cases("holdout"))
    random.Random(seed).shuffle(cases)
    return tuple(case.with_base_url(base_url) for case in cases)


def canonical_manifest(
    *, include_holdout: bool = False, seed: int = DEFAULT_SEED
) -> dict[str, Any]:
    """Build stable pre-run metadata without ports, provider data, or results."""
    cases = list(load_cases("development"))
    if include_holdout:
        cases.extend(load_cases("holdout"))
    random.Random(seed).shuffle(cases)
    return {
        "suite": "browski-task-mix-v1",
        "seed": seed,
        "order": [case.case_id for case in cases],
        "cases": [case.as_dict() for case in cases],
        "source_sha256": source_checksum(include_holdout=include_holdout),
    }


def source_checksum(*, include_holdout: bool = False) -> str:
    """Hash included data files in fixed split order."""
    if not include_holdout:
        return hashlib.sha256((DATA_DIR / "development.jsonl").read_bytes()).hexdigest()

    digest = hashlib.sha256()
    for split in ("development", "holdout"):
        digest.update(split.encode("ascii"))
        digest.update(b"\0")
        digest.update((DATA_DIR / f"{split}.jsonl").read_bytes())
    return digest.hexdigest()
