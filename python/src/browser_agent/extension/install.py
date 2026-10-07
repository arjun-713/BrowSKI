"""Install the Linux Chrome Native Messaging host manifest and launcher."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path

_HOST_NAME = "com.browski.runtime"
_EXTENSION_ID = re.compile(r"^[a-p]{32}$")


def _manifest_directory(browser: str) -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    if browser == "chrome":
        return config_home / "google-chrome" / "NativeMessagingHosts"
    return config_home / "chromium" / "NativeMessagingHosts"


def _write_atomic(path: Path, contents: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _validate_install_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("Native Messaging manifest path must be a directory")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError(
            "Native Messaging manifest directory must be user-owned and not group/world writable"
        )


def install_native_host(
    *,
    extension_id: str,
    browser: str,
    host_executable: Path,
    manifest_directory: Path | None = None,
) -> tuple[Path, Path]:
    """Write a user-scoped launcher and Chrome Native Messaging manifest."""
    if sys.platform != "linux":
        raise ValueError("the Native Messaging installer currently supports Linux only")
    if not _EXTENSION_ID.fullmatch(extension_id):
        raise ValueError("extension ID must be 32 lowercase characters from a through p")
    if browser not in {"chrome", "chromium"}:
        raise ValueError("browser must be chrome or chromium")
    if not host_executable.is_absolute() or not host_executable.is_file():
        raise ValueError("native host executable must be an existing absolute file path")

    directory = (manifest_directory or _manifest_directory(browser)).expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_install_directory(directory)

    wrapper = directory / "browski-native-host"
    manifest = directory / f"{_HOST_NAME}.json"
    wrapper_contents = (
        "#!/bin/sh\n"
        f"BROWSKI_EXTENSION_ID={shlex.quote(extension_id)}\n"
        "export BROWSKI_EXTENSION_ID\n"
        f'exec {shlex.quote(str(host_executable))} "$@"\n'
    ).encode()
    manifest_contents = (
        json.dumps(
            {
                "name": _HOST_NAME,
                "description": "BROWSKI local browser runtime bridge",
                "path": str(wrapper),
                "type": "stdio",
                "allowed_origins": [f"chrome-extension://{extension_id}/"],
            },
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )

    _write_atomic(wrapper, wrapper_contents, 0o700)
    _write_atomic(manifest, manifest_contents, 0o600)
    return wrapper, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Install BROWSKI's Chrome Native Messaging host")
    parser.add_argument("--extension-id", required=True, help="Exact installed extension ID")
    parser.add_argument("--browser", choices=("chrome", "chromium"), default="chrome")
    parser.add_argument(
        "--host-executable",
        type=Path,
        help="Absolute path to browski-native-host (defaults to PATH lookup)",
    )
    parser.add_argument(
        "--manifest-directory",
        type=Path,
        help="Override the current user's Chrome NativeMessagingHosts directory",
    )
    arguments = parser.parse_args()

    executable = arguments.host_executable
    if executable is None:
        located = shutil.which("browski-native-host")
        executable = Path(located) if located else None
    if executable is None:
        parser.error("browski-native-host is not installed or --host-executable was not provided")

    try:
        wrapper, manifest = install_native_host(
            extension_id=arguments.extension_id,
            browser=arguments.browser,
            host_executable=executable,
            manifest_directory=arguments.manifest_directory,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Installed BROWSKI Native Messaging wrapper: {wrapper}")
    print(f"Installed Chrome host manifest: {manifest}")


if __name__ == "__main__":
    main()
