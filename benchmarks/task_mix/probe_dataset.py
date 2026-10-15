"""Freeze and validate the synthetic Laya probe corpus."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmarks.task_mix.probe_cases_simple import simple_cases
from benchmarks.task_mix.probe_cases_workflows import workflow_cases
from benchmarks.task_mix.probe_packets import (
    PERMUTED_CASE_IDS,
    SEED,
    TEMPLATE_VERSION,
)

SCOPED_INSTRUCTIONS = (
    "Choose the next authorized user command. Prerequisites have been checked locally. "
    "Choose ESCALATE_TO_REASONER if the proposed operation is not safely justified."
)
SCOPED_AUTHORIZATION = "Exact target and value authorized locally by user instruction."
SCOPED_PREREQUISITES = "All preceding commands verified; target currently interactable."
SCOPED_ESCALATE_DESCRIPTION = "Ask the reasoning provider to review this decision."
SCOPED_EXECUTE_SUFFIXES = {
    "type": " using the exact locally authorized value",
    "select": " using the exact locally authorized value",
}


def frozen_cases() -> list[dict[str, Any]]:
    rows = simple_cases()
    rows.extend(workflow_cases())
    if len(rows) != 24:
        raise AssertionError(f"expected 24 frozen cases, got {len(rows)}")
    return rows


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _template_sha256() -> str:
    template = {
        "template_version": TEMPLATE_VERSION,
        "instructions": SCOPED_INSTRUCTIONS,
        "safe_command_description": {
            "label_encoding": "json.dumps(label[:120], ensure_ascii=True)",
            "prefix": "{kind} the user-named control ",
            "type_select_suffix": SCOPED_EXECUTE_SUFFIXES["type"],
            "check_suffix": " to checked={checked}",
            "other_suffix": "",
        },
        "authorization": SCOPED_AUTHORIZATION,
        "prerequisites": SCOPED_PREREQUISITES,
        "options": {
            "EXECUTE_AUTHORIZED_COMMAND": "{safe_command_description}",
            "ESCALATE_TO_REASONER": SCOPED_ESCALATE_DESCRIPTION,
        },
    }
    return hashlib.sha256(_canonical_json(template)).hexdigest()


def freeze(path: Path, manifest_path: Path) -> dict[str, Any]:
    if path.exists() or manifest_path.exists():
        raise FileExistsError(
            "frozen probe files already exist; preserve them and use a new path"
        )
    rows = frozen_cases()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as target:
        for row in rows:
            target.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": path.name,
        "dataset_sha256": _sha256(path),
        "case_count": len(rows),
        "seed": SEED,
        "template_version": TEMPLATE_VERSION,
        "scoped_template_sha256": _template_sha256(),
        "position_probe_case_ids": sorted(PERMUTED_CASE_IDS),
        "in_scope_case_count": sum(bool(row["in_scope"]) for row in rows),
        "out_of_scope_case_ids": [
            row["case_id"] for row in rows if not row["in_scope"]
        ],
        "network_calls_made": 0,
        "holdout_files_read": False,
    }
    with manifest_path.open("x", encoding="utf-8") as target:
        json.dump(manifest, target, ensure_ascii=False, indent=2)
        target.write("\n")
    return manifest


def load_frozen(
    path: Path, manifest_path: Path, expected_sha256: str
) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = _sha256(path)
    if actual != expected_sha256 or actual != manifest.get("dataset_sha256"):
        raise ValueError(
            "frozen probe SHA-256 does not match the manifest and explicit approval hash"
        )
    if manifest.get("scoped_template_sha256") != _template_sha256():
        raise ValueError("frozen probe scoped-template hash does not match this script")
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 24 or len({row["case_id"] for row in rows}) != 24:
        raise ValueError("frozen probe must contain exactly 24 unique cases")
    return rows
