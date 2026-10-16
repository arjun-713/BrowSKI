"""Read-only diagnostics cannot steal or tear down the extension connection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from browser_agent.extension.diagnostics import (
    DiagnosticRequest,
    inspect_attached_runtime,
    probe_runtime,
)
from browser_agent.extension.service import ExtensionBridgeService
from browser_agent.extension.wire import read_native_frame, write_native_frame
from browser_agent.session import BrowserSession


async def connect_extension(
    service: ExtensionBridgeService,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    await write_native_frame(
        writer, {"type": "runtime.auth", "token": service.token_path.read_text()}
    )
    await write_native_frame(
        writer,
        {
            "protocolVersion": 1,
            "type": "extension.hello",
            "eventId": str(uuid4()),
            "payload": {
                "protocolVersions": [1],
                "debuggerProtocolVersion": 1,
                "debuggerMethods": ["DOM.getDocument"],
                "debuggerEvents": [],
            },
        },
    )
    for expected in ("host.hello", "runtime.snapshot", "runtime.credentials.status"):
        assert (await read_native_frame(reader))["type"] == expected
    return reader, writer


@pytest.mark.asyncio
async def test_diagnostic_does_not_consume_or_close_extension_slot(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "runtime" / "bridge.sock")
    await service.start()
    reader, writer = await connect_extension(service)
    try:
        response = await probe_runtime(service.socket_path)
        assert response.checks[1].status == "PASS"
        assert response.checks[2].status == "WARN"
        await write_native_frame(
            writer,
            {
                "protocolVersion": 1,
                "type": "runtime.snapshot.request",
                "eventId": str(uuid4()),
                "payload": {"afterSequence": 0},
            },
        )
        assert (await read_native_frame(reader))["type"] == "runtime.snapshot"
    finally:
        writer.close()
        await writer.wait_closed()
        await service.close()


@pytest.mark.asyncio
async def test_unauthenticated_diagnostic_does_not_detach_extension(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "runtime" / "bridge.sock")
    await service.start()
    extension_reader, extension_writer = await connect_extension(service)
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    try:
        await write_native_frame(writer, {"type": "runtime.auth", "token": "wrong"})
        assert await asyncio.wait_for(reader.read(), timeout=3) == b""
        assert (await probe_runtime(service.socket_path)).checks[1].status == "PASS"
        await write_native_frame(
            extension_writer,
            {
                "protocolVersion": 1,
                "type": "runtime.snapshot.request",
                "eventId": str(uuid4()),
                "payload": {"afterSequence": 0},
            },
        )
        assert (await read_native_frame(extension_reader))["type"] == "runtime.snapshot"
    finally:
        writer.close()
        extension_writer.close()
        await writer.wait_closed()
        await extension_writer.wait_closed()
        await service.close()


@pytest.mark.asyncio
async def test_diagnostic_rejects_replay(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "runtime" / "bridge.sock")
    await service.start()
    request = DiagnosticRequest(request_id=str(uuid4()))
    try:
        for attempt in range(2):
            reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
            await write_native_frame(
                writer,
                {
                    "type": "runtime.auth",
                    "token": service.token_path.read_text(),
                },
            )
            await write_native_frame(writer, request.model_dump())
            if attempt == 0:
                assert (await read_native_frame(reader))["request_id"] == request.request_id
            else:
                assert await asyncio.wait_for(reader.read(), timeout=3) == b""
            writer.close()
            await writer.wait_closed()
    finally:
        await service.close()


class ProbeBrowser:
    session_id = "diagnostic-fixture-session"

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    async def probe_connection(self) -> None:
        self.calls.append("cdp")
        if self.fail:
            raise DisconnectedBrowser("private browser error should never leave the probe")

    async def observe(self) -> None:
        self.calls.append("observe")


class DisconnectedBrowser(RuntimeError):
    native_error_type = "CONNECTION_LOST"


@pytest.mark.asyncio
async def test_idle_diagnostic_separates_cdp_from_observation_without_models(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("browser_agent.credentials.configured_openai_api_key", lambda: None)
    browser = ProbeBrowser()
    response = await inspect_attached_runtime(
        request_id=str(uuid4()),
        browser=cast(BrowserSession, browser),
        extension_connected=True,
        run_owns_browser=False,
        config_path=None,
        database_path=tmp_path / "checkpoints.sqlite",
    )
    assert browser.calls == ["cdp", "observe"]
    checks = {item.name: item for item in response.checks}
    assert checks["CDP round-trip"].status == "PASS"
    assert checks["DOM observation"].status == "PASS"
    assert checks["Agent graph"].status == "PASS"
    assert checks["Runtime OpenAI configuration"].status == "WARN"
    assert not (tmp_path / "checkpoints.sqlite").exists()


@pytest.mark.asyncio
async def test_failed_cdp_probe_does_not_observe_or_leak_browser_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("browser_agent.credentials.configured_openai_api_key", lambda: None)
    browser = ProbeBrowser(fail=True)
    response = await inspect_attached_runtime(
        request_id=str(uuid4()),
        browser=cast(BrowserSession, browser),
        extension_connected=True,
        run_owns_browser=False,
        config_path=None,
        database_path=tmp_path / "checkpoints.sqlite",
    )
    assert browser.calls == ["cdp"]
    checks = {item.name: item for item in response.checks}
    assert checks["CDP round-trip"].detail == "probe failed: CONNECTION_LOST"
    assert "DOM observation" not in checks
    assert "private browser error" not in response.model_dump_json()


@pytest.mark.asyncio
async def test_diagnostic_never_touches_browser_during_suspended_run(tmp_path: Path) -> None:
    browser = ProbeBrowser()
    response = await inspect_attached_runtime(
        request_id=str(uuid4()),
        browser=cast(BrowserSession, browser),
        extension_connected=True,
        run_owns_browser=True,
        config_path=None,
        database_path=tmp_path / "checkpoints.sqlite",
    )
    assert browser.calls == []
    assert response.checks[-1].detail == "skipped while a run owns browser state"
