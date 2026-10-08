"""Tests for deterministic local release archive and checksum generation."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from scripts.release_artifacts import prepare


def _write_stage(root: Path) -> Path:
    extension = root / "extension" / "chrome-mv3"
    extension.mkdir(parents=True)
    (extension / "manifest.json").write_text(
        '{"manifest_version": 3}\n', encoding="utf-8"
    )
    (extension / "background.js").write_text(
        "self.addEventListener('install', () => {});\n"
    )
    wheel_directory = root / "python"
    wheel_directory.mkdir()
    (wheel_directory / "browser_agent-0.1.0-py3-none-any.whl").write_bytes(
        b"wheel fixture"
    )
    report_directory = root / "reports"
    report_directory.mkdir()
    (report_directory / "dependency-licenses.json").write_text("{}\n", encoding="utf-8")
    return root


def test_release_metadata_archive_and_checksums_are_deterministic(
    tmp_path: Path,
) -> None:
    first_stage = _write_stage(tmp_path / "first")
    second_stage = _write_stage(tmp_path / "second")

    prepare(first_stage, "0.1.0")
    prepare(second_stage, "0.1.0")

    first_archive = first_stage / "extension/browski-browser-extension-0.1.0.zip"
    second_archive = second_stage / "extension/browski-browser-extension-0.1.0.zip"
    assert first_archive.read_bytes() == second_archive.read_bytes()
    assert (first_stage / "release-manifest.json").read_bytes() == (
        second_stage / "release-manifest.json"
    ).read_bytes()
    checksums = (first_stage / "SHA256SUMS").read_bytes()
    assert checksums == (second_stage / "SHA256SUMS").read_bytes()
    manifest = json.loads(
        (first_stage / "release-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["published"] is False
    with zipfile.ZipFile(first_archive) as archive:
        assert archive.namelist() == [
            "chrome-mv3/background.js",
            "chrome-mv3/manifest.json",
        ]

    for line in checksums.decode("utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        assert (
            hashlib.sha256((first_stage / relative).read_bytes()).hexdigest() == digest
        )
