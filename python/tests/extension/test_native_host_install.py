"""Native Messaging host installation tests."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from browser_agent.extension.install import install_native_host


def test_install_writes_exact_origin_and_private_launcher(tmp_path: Path) -> None:
    host_executable = tmp_path / "browski-native-host"
    host_executable.write_text(
        '#!/bin/sh\nprintf "%s:%s" "$BROWSKI_EXTENSION_ID" "$1"\n',
        encoding="utf-8",
    )
    host_executable.chmod(0o700)
    manifest_directory = tmp_path / "NativeMessagingHosts"

    wrapper, manifest_path = install_native_host(
        extension_id="a" * 32,
        browser="chrome",
        host_executable=host_executable,
        manifest_directory=manifest_directory,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "name": "com.browski.runtime",
        "description": "BROWSKI local browser runtime bridge",
        "path": str(wrapper),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{'a' * 32}/"],
    }
    assert f"BROWSKI_EXTENSION_ID={'a' * 32}" in wrapper.read_text(encoding="utf-8")
    assert stat.S_IMODE(wrapper.stat().st_mode) == 0o700
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert manifest_path.parent.stat().st_uid == os.getuid()
    launched = subprocess.run(
        [str(wrapper), "chrome-extension://test/"],
        capture_output=True,
        check=True,
        text=True,
    )
    assert launched.stdout == f"{'a' * 32}:chrome-extension://test/"


@pytest.mark.parametrize(
    ("extension_id", "browser"),
    [("bad-id", "chrome"), ("a" * 32, "edge")],
)
def test_install_rejects_invalid_identity_or_browser(
    tmp_path: Path,
    extension_id: str,
    browser: str,
) -> None:
    host_executable = tmp_path / "host"
    host_executable.write_text("host", encoding="utf-8")

    with pytest.raises(ValueError):
        install_native_host(
            extension_id=extension_id,
            browser=browser,
            host_executable=host_executable,
            manifest_directory=tmp_path / "manifests",
        )


def test_install_rejects_directory_writable_by_other_users(tmp_path: Path) -> None:
    host_executable = tmp_path / "host"
    host_executable.write_text("host", encoding="utf-8")
    manifest_directory = tmp_path / "manifests"
    manifest_directory.mkdir(mode=0o777)
    manifest_directory.chmod(0o777)

    with pytest.raises(ValueError, match="not group/world writable"):
        install_native_host(
            extension_id="a" * 32,
            browser="chrome",
            host_executable=host_executable,
            manifest_directory=manifest_directory,
        )
