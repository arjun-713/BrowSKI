"""Task startup errors must settle as typed results rather than orphaned tasks."""

from __future__ import annotations

import asyncio
import json
from importlib import import_module
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from browser_agent.extension.service import ExtensionBridgeService


@pytest.mark.asyncio
async def test_attachment_wait_error_is_reported_with_private_safe_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    run_id = str(uuid4())
    service._run_id = run_id  # pyright: ignore[reportPrivateUsage]
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": "attachment-session",
        "runId": run_id,
        "status": "running",
        "updatedAt": "2026-10-16T00:00:00+00:00",
    }
    frames: list[dict[str, object]] = []

    class Writer:
        def is_closing(self) -> bool:
            return False

    async def fail_attachment() -> None:
        error = RuntimeError("private-cookie-fixture must not reach a result")
        for name, value in {
            "component": "browser_core",
            "operation": "observe",
            "native_error_type": "CONNECTION_LOST",
            "failure_kind": "EXECUTION",
            "recoverable": False,
        }.items():
            setattr(error, name, value)
        raise error

    async def capture(_writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        frames.append(message)

    monkeypatch.setattr(service, "wait_for_attached_browser", fail_attachment)
    monkeypatch.setattr(
        import_module("browser_agent.extension.service"), "_write_native_frame", capture
    )
    await service._run_attached_task(  # pyright: ignore[reportPrivateUsage]
        cast(asyncio.StreamWriter, Writer()),
        "Synthetic task",
        run_id,
    )
    assert service.runtime_session is not None
    assert service.runtime_session["status"] == "failed"
    timeline = [item for item in frames if item["type"] == "runtime.timeline"]
    results = [item for item in frames if item["type"] == "runtime.task.result"]
    assert len(timeline) == len(results) == 1
    event = cast(dict[str, object], cast(dict[str, object], timeline[0]["payload"])["event"])
    payload = cast(dict[str, object], results[0]["payload"])
    failure = cast(dict[str, object], payload["failure"])
    assert payload["runId"] == run_id
    assert event["failure"] == failure
    assert failure["nativeErrorType"] == "CONNECTION_LOST"
    assert "private-cookie-fixture" not in json.dumps(frames)
    assert failure["safeMessage"] == payload["summary"]
