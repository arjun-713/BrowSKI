"""Retain a source/native snapshot beside local results before model inference."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_SOURCE_SUFFIXES = {".py", ".pyi", ".so", ".toml", ".json"}


def freeze_runtime(output: Path, *, label: str = "browski-task-mix-runtime") -> None:
    root = Path(__file__).resolve().parents[2]
    source = root / "python/src/browser_agent"
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    package = output / "browser_agent"
    files: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix not in _SOURCE_SUFFIXES:
            continue
        name = path.relative_to(source)
        target = package / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        files[str(name)] = hashlib.sha256(target.read_bytes()).hexdigest()
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    versions = {}
    for dependency in ("openai", "pydantic", "langgraph", "maturin"):
        try:
            versions[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError:
            versions[dependency] = None
    manifest = {
        "runtime": label,
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": revision,
        "working_tree_changes_included": True,
        "python": sys.version,
        "dependencies": versions,
        "files": files,
        "lockfiles": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (root / "Cargo.lock", root / "python/uv.lock")
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    print(f"Retained {len(files)} runtime files at {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="browski-task-mix-runtime")
    args = parser.parse_args()
    freeze_runtime(args.output, label=args.label)


if __name__ == "__main__":
    main()
