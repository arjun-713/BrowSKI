"""Native host starts the local runtime once, beside itself, with a bounded wait."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from browser_agent.extension import native_host
from browser_agent.extension.native_host import (
    NativeHostError,
    _runtime_working_directory,  # pyright: ignore[reportPrivateUsage]
    start_runtime_service,
)


def test_source_install_runs_the_service_from_the_repository_root(tmp_path: Path) -> None:
    (tmp_path / "python" / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / "python" / "pyproject.toml").write_text("[project]\n")
    interpreter = tmp_path / "python" / ".venv" / "bin" / "python"
    assert _runtime_working_directory(interpreter) == tmp_path


def test_other_installs_run_the_service_from_home(tmp_path: Path) -> None:
    interpreter = tmp_path / "opt" / "bin" / "python"
    assert _runtime_working_directory(interpreter) == Path.home()


def test_missing_runtime_executable_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(NativeHostError, match="not installed"):
        start_runtime_service(tmp_path / "bridge.sock", executable=tmp_path / "python")


def test_start_waits_a_bounded_time_and_launches_serve_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "started"
    browski = tmp_path / "browski"
    browski.write_text(f'#!/bin/sh\necho "$@" >> {marker}\n')
    browski.chmod(0o700)
    monkeypatch.setattr(native_host, "_SERVICE_START_SECONDS", 0.5)
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(NativeHostError, match="did not start in time"):
        start_runtime_service(tmp_path / "bridge.sock", executable=tmp_path / "python")
    assert marker.read_text().split() == ["serve", "--socket-path", str(tmp_path / "bridge.sock")]
    log = tmp_path / ".local" / "state" / "browski" / "backend.log"
    assert os.stat(log).st_mode & 0o077 == 0


def test_leftover_socket_from_a_stopped_service_is_not_ready(tmp_path: Path) -> None:
    # Regression: a stopped service left bridge.sock and its token behind; the
    # host saw the files, skipped autostart, and the panel stayed offline.
    import socket

    from browser_agent.extension.native_host import runtime_ready

    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(mode=0o700)
    socket_path = runtime_dir / "bridge.sock"
    token = socket_path.with_suffix(".token")
    token.write_text("t" * 43)
    token.chmod(0o600)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    socket_path.chmod(0o600)
    listener.listen(1)
    try:
        assert runtime_ready(socket_path)
    finally:
        listener.close()
    assert socket_path.exists(), "the stale socket file remains, as after a crash"
    assert not runtime_ready(socket_path)
