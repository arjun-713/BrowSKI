#!/usr/bin/env python3
"""Report declared licenses for locked Rust, Python, and npm dependencies.

This inventories package metadata; it is not a legal license review.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_COPYLEFT_MARKERS = re.compile(
    r"(?:^|[^A-Z])(?:AGPL|GPL|LGPL|SSPL|MPL|EPL|CDDL)(?:[- .]|$)", re.IGNORECASE
)


def classify_license(value: object) -> str:
    """Classify a declaration conservatively without interpreting SPDX logic."""
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    if _COPYLEFT_MARKERS.search(value):
        return "copyleft_or_reciprocal"
    return "declared"


def _cargo_packages(repository: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [
            "cargo",
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--manifest-path",
            str(repository / "Cargo.toml"),
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    metadata_document = json.loads(result.stdout)
    packages = metadata_document.get("packages")
    if not isinstance(packages, list):
        raise TypeError("cargo metadata returned no package list")
    return [
        {
            "name": package.get("name"),
            "version": package.get("version"),
            "license": package.get("license"),
            "license_file": package.get("license_file"),
            "source": package.get("source") or "workspace",
            "classification": classify_license(package.get("license")),
        }
        for package in packages
    ]


def _python_distributions(python_executable: Path) -> list[dict[str, Any]]:
    script = r"""
import json
from importlib import metadata

rows = []
for distribution in metadata.distributions():
    package_metadata = distribution.metadata
    name = package_metadata.get("Name") or distribution.name or "unknown"
    license_value = package_metadata.get("License-Expression") or package_metadata.get("License")
    if not license_value:
        classifiers = [
            item.removeprefix("License :: ")
            for item in package_metadata.get_all("Classifier", [])
            if item.startswith("License :: ")
        ]
        license_value = "; ".join(classifiers) if classifiers else None
    rows.append({
            "name": name,
            "version": distribution.version,
            "license": license_value,
        })
print(json.dumps(rows))
"""
    result = subprocess.run(
        [str(python_executable), "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(result.stdout)
    for row in rows:
        row["classification"] = classify_license(row.get("license"))
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["version"]))


def _npm_distributions(repository: Path) -> list[dict[str, Any]]:
    extension = repository / "extension"
    lock_path = extension / "package-lock.json"
    if not lock_path.is_file():
        raise RuntimeError(f"missing npm lockfile: {lock_path}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages")
    if not isinstance(packages, dict):
        raise TypeError("npm package-lock.json does not contain a packages map")

    result: list[dict[str, Any]] = []
    for package_path, locked in sorted(packages.items()):
        if not package_path:
            continue
        if not isinstance(locked, dict):
            continue
        installed_path = extension / package_path / "package.json"
        installed: dict[str, Any] = {}
        if installed_path.is_file():
            try:
                loaded = json.loads(installed_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    installed = loaded
            except (OSError, json.JSONDecodeError):
                installed = {}
        license_value = installed.get("license") or locked.get("license")
        result.append(
            {
                "name": locked.get("name")
                or installed.get("name")
                or package_path.rsplit("node_modules/", 1)[-1],
                "version": locked.get("version"),
                "license": license_value,
                "lock_path": package_path,
                "installed_metadata": installed_path.is_file(),
                "classification": classify_license(license_value),
            }
        )
    return result


def build_inventory(repository: Path, python_executable: Path) -> dict[str, Any]:
    sections = {
        "rust": _cargo_packages(repository),
        "python": _python_distributions(python_executable),
        "npm": _npm_distributions(repository),
    }
    summary = {
        ecosystem: {
            "packages": len(packages),
            "unknown": sum(item["classification"] == "unknown" for item in packages),
            "copyleft_or_reciprocal": sum(
                item["classification"] == "copyleft_or_reciprocal" for item in packages
            ),
        }
        for ecosystem, packages in sections.items()
    }
    return {
        "schema_version": 1,
        "generated_by": "scripts/license_inventory.py",
        "notice": (
            "Declared package metadata only. This is not a legal license review; "
            "verify package contents, obligations, and distribution terms before release."
        ),
        "summary": summary,
        "packages": sections,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory declared dependency licenses from locked project metadata.",
        epilog="Unknown or reciprocal declarations need human review; no legal conclusion is made.",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python environment to inspect (defaults to this interpreter).",
    )
    parser.add_argument(
        "--output", type=Path, help="Write the JSON inventory to this path."
    )
    args = parser.parse_args(argv)

    try:
        # Preserve the venv launcher path: resolving its symlink points at the
        # base interpreter and drops the venv's site-packages from discovery.
        inventory = build_inventory(
            args.repo.resolve(), args.python.expanduser().absolute()
        )
        rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (
        OSError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        RuntimeError,
        TypeError,
    ) as exc:
        print(f"license inventory failed: {exc}", file=sys.stderr)
        return 1

    for ecosystem, counts in inventory["summary"].items():
        print(
            f"{ecosystem}: {counts['packages']} packages, "
            f"{counts['unknown']} unknown, "
            f"{counts['copyleft_or_reciprocal']} reciprocal/copyleft",
            file=sys.stderr,
        )
    if args.output:
        print(f"Inventory written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
