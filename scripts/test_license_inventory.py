"""Tests for the dependency license metadata inventory."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.license_inventory import _npm_distributions, classify_license


def test_license_declaration_classification_is_conservative() -> None:
    assert classify_license("MIT") == "declared"
    assert classify_license("GPL-3.0-only") == "copyleft_or_reciprocal"
    assert classify_license(None) == "unknown"
    assert classify_license("") == "unknown"


def test_npm_inventory_joins_locked_and_installed_metadata(tmp_path: Path) -> None:
    extension = tmp_path / "extension"
    package_path = "node_modules/example-package"
    (extension / package_path).mkdir(parents=True)
    (extension / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "": {"name": "fixture", "version": "0.1.0"},
                    package_path: {"version": "1.2.3"},
                    "node_modules/locked-only": {
                        "version": "4.5.6",
                        "license": "Apache-2.0",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (extension / package_path / "package.json").write_text(
        json.dumps({"name": "example-package", "version": "1.2.3", "license": "MIT"}),
        encoding="utf-8",
    )

    rows = _npm_distributions(tmp_path)

    assert rows == [
        {
            "name": "example-package",
            "version": "1.2.3",
            "license": "MIT",
            "lock_path": package_path,
            "installed_metadata": True,
            "classification": "declared",
        },
        {
            "name": "locked-only",
            "version": "4.5.6",
            "license": "Apache-2.0",
            "lock_path": "node_modules/locked-only",
            "installed_metadata": False,
            "classification": "declared",
        },
    ]
