"""Create deterministic ZIP, release metadata, and checksums for a staged build."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path


def create_extension_archive(stage: Path, version: str) -> Path:
    extension = stage / "extension" / "chrome-mv3"
    if not (extension / "manifest.json").is_file():
        raise FileNotFoundError(f"production manifest is missing from {extension}")
    archive = stage / "extension" / f"browski-browser-extension-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        for path in sorted(extension.rglob("*")):
            if not path.is_file():
                continue
            relative = Path("chrome-mv3") / path.relative_to(extension)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            output.writestr(info, path.read_bytes())
    return archive


def write_release_metadata(stage: Path, version: str, archive: Path) -> Path:
    wheels = sorted(path.name for path in (stage / "python").glob("*.whl"))
    if not wheels:
        raise FileNotFoundError(f"no Python wheel was found in {stage / 'python'}")
    manifest = {
        "name": "BROWSKI local release artifacts",
        "version": version,
        "published": False,
        "builds": [
            "cargo build --workspace --release --locked",
            "uv build --wheel --no-build-isolation",
            "npm ci",
            "npm run build",
        ],
        "rust_component": "The configured PyO3 extension is included in the Python wheel.",
        "python_wheels": wheels,
        "extension_directory": "extension/chrome-mv3",
        "extension_archive": archive.relative_to(stage).as_posix(),
        "dependency_license_inventory": "reports/dependency-licenses.json",
        "checksums": "SHA256SUMS",
    }
    manifest_path = stage / "release-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest_path


def write_checksums(stage: Path) -> Path:
    checksum_file = stage / "SHA256SUMS"
    files = sorted(
        path for path in stage.rglob("*") if path.is_file() and path != checksum_file
    )
    with checksum_file.open("w", encoding="utf-8", newline="\n") as output:
        for path in files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            output.write(f"{digest}  {path.relative_to(stage).as_posix()}\n")
    return checksum_file


def prepare(stage: Path, version: str) -> None:
    archive = create_extension_archive(stage, version)
    write_release_metadata(stage, version, archive)
    write_checksums(stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a deterministic extension ZIP and checksums in a staged release directory."
    )
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        prepare(args.stage, args.version)
    except OSError as exc:
        print(f"release artifact packaging failed: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared release metadata and SHA256SUMS in {args.stage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
