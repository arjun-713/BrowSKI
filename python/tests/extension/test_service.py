"""Authenticated local extension bridge service tests."""

from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path
from typing import Literal, cast

import pytest

from browser_agent._types import TaskState
from browser_agent.extension.backend import Attachment, ExtensionCdpBackend
from browser_agent.extension.native_messaging import read_native_message, write_native_message
from browser_agent.extension.service import BridgeServiceError, ExtensionBridgeService


async def _read_message(reader: asyncio.StreamReader) -> dict[str, object]:
    header = await reader.readexactly(4)
    length = int.from_bytes(header, "little")
    payload = await reader.readexactly(length)
    message = read_native_message(io.BytesIO(header + payload))
    assert message is not None
    return message


def _write_message(message: dict[str, object]) -> bytes:
    frame = io.BytesIO()
    write_native_message(frame, message)
    return frame.getvalue()


def _envelope(event_id: str, message_type: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "protocolVersion": 1,
        "type": message_type,
        "eventId": event_id,
        "payload": payload,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["paused", "stopped"])
async def test_runtime_reports_pause_and_stop_as_distinct_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: Literal["paused", "stopped"],
) -> None:
    from importlib import import_module

    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    # Direct state setup isolates wire reporting from browser/model work.
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": "test-session",
        "status": "running",
        "updatedAt": "2026-10-08T00:00:00+00:00",
    }
    frames: list[dict[str, object]] = []

    class WriterStub:
        def is_closing(self) -> bool:
            return False

    async def capture_frame(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        del writer
        frames.append(message)

    monkeypatch.setattr(
        import_module("browser_agent.extension.service"), "_write_native_frame", capture_frame
    )
    await service._handle_task_result(  # pyright: ignore[reportPrivateUsage]
        cast(asyncio.StreamWriter, WriterStub()), TaskState(task="Synthetic task", status=status)
    )
    assert service.runtime_session is not None
    assert service.runtime_session["status"] == status
    assert service._runtime_suspended is (status == "paused")  # pyright: ignore[reportPrivateUsage]
    results = [frame for frame in frames if frame["type"] == "runtime.task.result"]
    if status == "paused":
        assert not results
    else:
        assert len(results) == 1
        assert cast(dict[str, object], results[0]["payload"])["outcome"] == "stopped"


@pytest.mark.asyncio
async def test_user_stop_persists_terminal_result_before_detaching_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib import import_module

    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": "test-session",
        "status": "running",
        "updatedAt": "2026-10-08T00:00:00+00:00",
    }
    service._run_id = "test-run"  # pyright: ignore[reportPrivateUsage]
    events: list[str] = []

    class WriterStub:
        def is_closing(self) -> bool:
            return False

    class RuntimeStub:
        async def stop(self, run_id: str) -> TaskState:
            assert run_id == "test-run"
            return TaskState(task="Synthetic task", run_id=run_id, status="stopped")

    class ContextStub:
        async def __aexit__(self, *args: object) -> None:
            events.append("context-closed")

    class BrowserSessionStub:
        async def close(self) -> None:
            events.append("browser-detached")

    async def capture_frame(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        del writer
        if message["type"] == "runtime.task.result":
            events.append("terminal-result")

    monkeypatch.setattr(
        import_module("browser_agent.extension.service"), "_write_native_frame", capture_frame
    )
    service._agent_runtime = RuntimeStub()  # pyright: ignore[reportPrivateUsage]
    service._runtime_context = ContextStub()  # pyright: ignore[reportPrivateUsage]
    service._browser_session = BrowserSessionStub()  # pyright: ignore[reportPrivateUsage]

    await service._stop_attached_task(  # pyright: ignore[reportPrivateUsage]
        cast(asyncio.StreamWriter, WriterStub()), "test-run"
    )

    assert events == ["terminal-result", "context-closed", "browser-detached"]
    assert service.runtime_session is None
    assert service._browser_session is None  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_service_authenticates_native_host_and_negotiates_supported_cdp_capabilities(
    tmp_path: Path,
) -> None:
    service = ExtensionBridgeService(tmp_path / "browski" / "bridge.sock")
    await service.start()
    token = service.token_path.read_text(encoding="ascii")
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    try:
        writer.write(_write_message({"type": "runtime.auth", "token": token}))
        writer.write(
            _write_message(
                _envelope(
                    "hello-1",
                    "extension.hello",
                    {
                        "protocolVersions": [1],
                        "debuggerProtocolVersion": 1,
                        "debuggerMethods": ["DOM.getDocument"],
                        "debuggerEvents": ["Page.loadEventFired"],
                    },
                )
            )
        )
        await writer.drain()

        host_hello = await _read_message(reader)
        runtime_snapshot = await _read_message(reader)
        credential_status = await _read_message(reader)
        assert host_hello["type"] == "host.hello"
        host_payload = cast(dict[str, object], host_hello["payload"])
        assert host_payload["debuggerMethods"] == ["DOM.getDocument"]
        assert host_payload["debuggerEvents"] == ["Page.loadEventFired"]
        snapshot_payload = cast(dict[str, object], runtime_snapshot["payload"])
        session = cast(dict[str, object], snapshot_payload["session"])
        # ADR-032: side-panel tasks default to General acting in the user's own tabs.
        assert session["engine"] == "general"
        assert session["provider"] == "openai"
        assert session["browserMode"] == "attached"
        assert session["status"] == "idle"
        assert snapshot_payload["events"] == []
        assert snapshot_payload["pendingApproval"] is None
        assert credential_status["type"] == "runtime.credentials.status"

        writer.write(
            _write_message(
                _envelope(
                    "snapshot-1",
                    "runtime.snapshot.request",
                    {"afterSequence": 0},
                )
            )
        )
        await writer.drain()
        assert (await _read_message(reader))["type"] == "runtime.snapshot"
    finally:
        writer.close()
        await writer.wait_closed()
        await service.close()

    assert not service.socket_path.exists()
    assert not service.token_path.exists()


@pytest.mark.asyncio
async def test_credentials_are_saved_through_injected_store_and_status_is_secret_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BROWSKI_OPENAI_API_KEY", raising=False)

    class MemoryCredentialStore:
        value: str | None = None

        def get_openai_api_key(self) -> str | None:
            return self.value

        def set_openai_api_key(self, api_key: str) -> None:
            self.value = api_key

        def delete_openai_api_key(self) -> None:
            self.value = None

    store = MemoryCredentialStore()
    service = ExtensionBridgeService(
        tmp_path / "browski" / "bridge.sock",
        credential_store=store,
    )
    await service.start()
    token = service.token_path.read_text(encoding="ascii")
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    secret = "sk-test-never-echo-this"
    try:
        writer.write(_write_message({"type": "runtime.auth", "token": token}))
        writer.write(
            _write_message(
                _envelope(
                    "hello-credentials",
                    "extension.hello",
                    {
                        "protocolVersions": [1],
                        "debuggerProtocolVersion": 1,
                        "debuggerMethods": ["DOM.getDocument"],
                        "debuggerEvents": ["Page.loadEventFired"],
                    },
                )
            )
        )
        await writer.drain()
        await _read_message(reader)
        await _read_message(reader)
        initial_status = await _read_message(reader)
        assert initial_status["payload"] == {"openAiKeyConfigured": False}

        writer.write(
            _write_message(
                _envelope("credential-set", "runtime.credentials.set", {"apiKey": secret})
            )
        )
        await writer.drain()
        saved_status = await _read_message(reader)
        assert store.value == secret
        assert saved_status["payload"] == {"openAiKeyConfigured": True}
        assert secret not in repr(saved_status)
    finally:
        writer.close()
        await writer.wait_closed()
        await service.close()


@pytest.mark.asyncio
async def test_service_rejects_a_second_runtime_for_the_same_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "browski" / "bridge.sock"
    first = ExtensionBridgeService(socket_path)
    second = ExtensionBridgeService(socket_path)
    await first.start()

    try:
        with pytest.raises(BridgeServiceError, match="could not create"):
            await second.start()
    finally:
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_service_shutdown_closes_active_native_host_connection(tmp_path: Path) -> None:
    service = ExtensionBridgeService(tmp_path / "browski" / "bridge.sock")
    await service.start()
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    await asyncio.sleep(0)

    await service.close()

    assert await asyncio.wait_for(reader.read(), timeout=2) == b""
    writer.close()
    await writer.wait_closed()
    with pytest.raises(BridgeServiceError, match="cannot be restarted"):
        await service.start()


@pytest.mark.asyncio
async def test_native_host_connects_to_service_and_relays_protocol_frames(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "browski" / "bridge.sock"
    service = ExtensionBridgeService(socket_path)
    await service.start()
    environment = os.environ.copy()
    environment["BROWSKI_EXTENSION_ID"] = "a" * 32
    environment["BROWSKI_RUNTIME_SOCKET"] = str(socket_path)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "browser_agent.extension.native_host",
        f"chrome-extension://{'a' * 32}/",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=environment,
    )
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(
            _write_message(
                _envelope(
                    "hello-1",
                    "extension.hello",
                    {
                        "protocolVersions": [1],
                        "debuggerProtocolVersion": 1,
                        "debuggerMethods": ["DOM.getDocument"],
                        "debuggerEvents": ["Page.loadEventFired"],
                    },
                )
            )
        )
        await process.stdin.drain()

        host_hello = await asyncio.wait_for(_read_message(process.stdout), timeout=5)
        runtime_snapshot = await asyncio.wait_for(_read_message(process.stdout), timeout=5)
        credential_status = await asyncio.wait_for(_read_message(process.stdout), timeout=5)
        assert host_hello["type"] == "host.hello"
        assert runtime_snapshot["type"] == "runtime.snapshot"
        snapshot_payload = cast(dict[str, object], runtime_snapshot["payload"])
        session = cast(dict[str, object], snapshot_payload["session"])
        # ADR-032: side-panel tasks default to General acting in the user's own tabs.
        assert session["engine"] == "general"
        assert session["provider"] == "openai"
        assert session["browserMode"] == "attached"
        assert session["status"] == "idle"
        assert snapshot_payload["events"] == []
        assert snapshot_payload["pendingApproval"] is None
        assert credential_status["type"] == "runtime.credentials.status"
    finally:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
        await service.close()


@pytest.mark.asyncio
async def test_confirmed_attachment_starts_shared_browser_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from browser_agent.session import BrowserSession

    calls: list[dict[str, object]] = []

    class FakeBrowserSession:
        async def close(self) -> None:
            return None

    async def attach_extension(cls: type[BrowserSession], **kwargs: object) -> FakeBrowserSession:
        del cls
        calls.append(kwargs)
        return FakeBrowserSession()

    monkeypatch.setattr(BrowserSession, "attach_extension", classmethod(attach_extension))
    service = ExtensionBridgeService(tmp_path / "browski" / "bridge.sock")
    await service.start()
    token = service.token_path.read_text(encoding="ascii")
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))
    try:
        writer.write(_write_message({"type": "runtime.auth", "token": token}))
        writer.write(
            _write_message(
                _envelope(
                    "hello-attach",
                    "extension.hello",
                    {
                        "protocolVersions": [1],
                        "debuggerProtocolVersion": 1,
                        "debuggerMethods": ["Page.enable", "DOM.enable"],
                        "debuggerEvents": ["Page.loadEventFired"],
                    },
                )
            )
        )
        await writer.drain()
        await _read_message(reader)
        await _read_message(reader)
        assert (await _read_message(reader))["type"] == "runtime.credentials.status"

        writer.write(
            _write_message(
                _envelope(
                    "attached-1",
                    "browser.tab.attached",
                    {
                        "attachmentId": "attachment-1",
                        "tabId": 9,
                        "origin": "https://jobs.example",
                        "sessionId": "runtime-session-1",
                    },
                )
            )
        )
        await writer.drain()
        snapshot = await _read_message(reader)
        await service.wait_for_attached_browser()

        snapshot_payload = cast(dict[str, object], snapshot["payload"])
        snapshot_session = cast(dict[str, object], snapshot_payload["session"])
        assert snapshot_session["sessionId"] == "runtime-session-1"
        assert calls == [
            {
                "socket_path": str(service.backend_socket_path),
                "token": token,
                "attachment_id": "attachment-1",
                "session_id": "runtime-session-1",
                "target_id": "extension-tab-attachment-1",
                "title": "Attached browser tab",
                "url": "about:blank",
                "browser_code_enabled": False,
            }
        ]

        writer.write(
            _write_message(
                _envelope(
                    "detached-1",
                    "browser.tab.detached",
                    {"attachmentId": "attachment-1", "reason": "user"},
                )
            )
        )
        await writer.drain()
        await _read_message(reader)
        assert service.runtime_session is None
    finally:
        writer.close()
        await writer.wait_closed()
        await service.close()


@pytest.mark.asyncio
async def test_attachment_initialization_failure_clears_owner_before_notifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from browser_agent.session import BrowserSession

    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    attachment = Attachment("attachment-failed", 12, "session-failed")
    backend = ExtensionCdpBackend(tmp_path / "backend.sock", "token")
    backend.set_attachment(attachment)
    service._backend = backend  # pyright: ignore[reportPrivateUsage]
    service._attachment_task = asyncio.current_task()  # pyright: ignore[reportPrivateUsage]
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": attachment.session_id,
        "status": "idle",
    }
    notifications: list[str] = []

    async def fail_attach(
        cls: type[BrowserSession],
        **kwargs: object,
    ) -> BrowserSession:
        del cls, kwargs
        raise RuntimeError("synthetic browser initialization failure")

    class WriterStub:
        def is_closing(self) -> bool:
            return False

    async def fail_detach(
        writer: asyncio.StreamWriter,
        attachment_id: str,
        reason: str,
    ) -> None:
        del writer, reason
        assert attachment_id == attachment.attachment_id
        assert service._attachment_task is None  # pyright: ignore[reportPrivateUsage]
        assert service.runtime_session is None
        assert backend.attachment is None
        notifications.append("detach")
        raise ConnectionResetError("synthetic native writer reset")

    async def fail_snapshot(writer: asyncio.StreamWriter) -> None:
        del writer
        notifications.append("snapshot")
        raise ConnectionResetError("synthetic native writer reset")

    monkeypatch.setattr(BrowserSession, "attach_extension", fail_attach)
    monkeypatch.setattr(service, "_send_detach", fail_detach)
    monkeypatch.setattr(service, "_send_runtime_snapshot", fail_snapshot)

    await service._open_attached_browser(  # pyright: ignore[reportPrivateUsage]
        cast(asyncio.StreamWriter, WriterStub()), attachment
    )

    assert notifications == ["detach", "snapshot"]
    assert service._attachment_task is None  # pyright: ignore[reportPrivateUsage]
    assert service._backend.attachment is None  # pyright: ignore[reportPrivateUsage]
    assert service.runtime_session is None


@pytest.mark.asyncio
async def test_runtime_settings_get_and_update_use_typed_config_without_model_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    frames: list[dict[str, object]] = []

    class WriterStub:
        def is_closing(self) -> bool:
            return False

    async def capture_frame(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        del writer
        frames.append(message)

    monkeypatch.setattr(
        service._settings_service,  # pyright: ignore[reportPrivateUsage]
        "_write_frame",
        capture_frame,
    )
    from importlib import import_module

    monkeypatch.setattr(
        import_module("browser_agent.extension.service"), "_write_native_frame", capture_frame
    )
    writer = cast(asyncio.StreamWriter, WriterStub())
    await service._handle_message(  # pyright: ignore[reportPrivateUsage]
        writer,
        {"type": "runtime.settings.get", "payload": {}},
    )
    initial = cast(dict[str, object], frames[-1]["payload"])
    assert frames[-1]["type"] == "runtime.settings.status"
    assert initial["effort"] == "low"
    assert initial["layaMode"] == "shadow"
    assert initial["confirmHighRiskActions"] is True
    assert initial["extensionTransport"] == "native_host"

    await service._handle_message(  # pyright: ignore[reportPrivateUsage]
        writer,
        {
            "type": "runtime.settings.update",
            "payload": {
                "effort": "none",
                "privacyMode": "offline",
                "layaMode": "disabled",
                "traceLevel": "detailed",
            },
        },
    )
    status_frame = next(
        frame for frame in reversed(frames) if frame["type"] == "runtime.settings.status"
    )
    updated = cast(dict[str, object], status_frame["payload"])
    assert updated["effort"] == "none"
    assert updated["privacyMode"] == "offline"
    assert updated["layaMode"] == "disabled"
    assert updated["traceLevel"] == "detailed"
    assert updated["confirmHighRiskActions"] is True
    assert (tmp_path / "xdg/browski/config.toml").is_file()


@pytest.mark.asyncio
async def test_runtime_settings_cannot_change_while_a_task_is_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    service = ExtensionBridgeService(tmp_path / "bridge.sock", config_path=config_path)
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": "session-1",
        "status": "paused",
    }
    service._runtime_suspended = True  # pyright: ignore[reportPrivateUsage]
    frames: list[dict[str, object]] = []

    class WriterStub:
        def is_closing(self) -> bool:
            return False

    async def capture_frame(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        del writer
        frames.append(message)

    monkeypatch.setattr(
        service._settings_service,  # pyright: ignore[reportPrivateUsage]
        "_write_frame",
        capture_frame,
    )
    await service._handle_message(  # pyright: ignore[reportPrivateUsage]
        cast(asyncio.StreamWriter, WriterStub()),
        {
            "type": "runtime.settings.update",
            "payload": {
                "effort": "low",
                "privacyMode": "standard",
                "layaMode": "shadow",
                "traceLevel": "standard",
            },
        },
    )

    response = cast(dict[str, object], frames[-1]["payload"])
    assert frames[-1]["type"] == "runtime.settings.status"
    assert response["error"] == "Runtime settings cannot be changed while a task is active."
    assert not config_path.exists()


@pytest.mark.asyncio
async def test_native_messaging_attach_initializes_and_detaches_rust_session(
    tmp_path: Path,
) -> None:
    from browser_agent.session import BrowserSession

    methods = ["Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"]
    service = ExtensionBridgeService(tmp_path / "browski" / "bridge.sock")
    await service.start()
    token = service.token_path.read_text(encoding="ascii")
    reader, writer = await asyncio.open_unix_connection(str(service.socket_path))

    async def send(event_id: str, message_type: str, payload: dict[str, object]) -> None:
        writer.write(_write_message(_envelope(event_id, message_type, payload)))
        await writer.drain()

    try:
        writer.write(_write_message({"type": "runtime.auth", "token": token}))
        writer.write(
            _write_message(
                _envelope(
                    "hello-integrated",
                    "extension.hello",
                    {
                        "protocolVersions": [1],
                        "debuggerProtocolVersion": 1,
                        "debuggerMethods": methods,
                        "debuggerEvents": ["Page.loadEventFired"],
                    },
                )
            )
        )
        await writer.drain()
        await _read_message(reader)
        await _read_message(reader)
        assert (await _read_message(reader))["type"] == "runtime.credentials.status"
        await send(
            "attach-integrated",
            "browser.tab.attached",
            {
                "attachmentId": "attachment-integrated",
                "tabId": 12,
                "origin": "https://example.test",
                "sessionId": "runtime-session-integrated",
            },
        )
        attached = await asyncio.wait_for(_read_message(reader), timeout=5)
        attached_payload = cast(dict[str, object], attached["payload"])
        attached_session = cast(dict[str, object], attached_payload["session"])
        assert attached_session["sessionId"] == "runtime-session-integrated"

        received: set[str] = set()
        sequence = 0
        while received != set(methods):
            command = await asyncio.wait_for(_read_message(reader), timeout=5)
            assert command["type"] == "debugger.command"
            payload = cast(dict[str, object], command["payload"])
            method = payload["method"]
            assert isinstance(method, str)
            received.add(method)
            sequence += 1
            await send(
                f"result-integrated-{sequence}",
                "debugger.command.result",
                {
                    "attachmentId": "attachment-integrated",
                    "sessionId": "runtime-session-integrated",
                    "commandId": payload["commandId"],
                    "result": {},
                },
            )

        browser = await service.wait_for_attached_browser()
        assert isinstance(browser, BrowserSession)
        assert browser.session_id == "runtime-session-integrated"
        await send(
            "detach-integrated",
            "browser.tab.detached",
            {"attachmentId": "attachment-integrated", "reason": "user"},
        )
        detached = await asyncio.wait_for(_read_message(reader), timeout=5)
        detached_payload = cast(dict[str, object], detached["payload"])
        assert detached_payload["session"] is None
        assert service.runtime_session is None
        assert await service.wait_for_attached_browser() is None
    finally:
        writer.close()
        await writer.wait_closed()
        await service.close()


@pytest.mark.parametrize(
    "status,outcome",
    [
        ("completed", "verified_success"),
        ("partially_completed", "partially_completed"),
        ("blocked", "blocked"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
async def test_managed_terminal_result_is_retained_for_snapshot_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    outcome: str,
) -> None:
    from importlib import import_module

    service = ExtensionBridgeService(tmp_path / "bridge.sock")
    service._runtime_session = {  # pyright: ignore[reportPrivateUsage]
        "sessionId": "managed",
        "status": "running",
        "browserMode": "managed",
        "engine": "fast",
        "provider": "laya",
        "updatedAt": "2026-10-18T00:00:00Z",
    }
    service._run_id = "managed-run"  # pyright: ignore[reportPrivateUsage]
    frames: list[dict[str, object]] = []

    class Writer:
        def is_closing(self) -> bool:
            return False

    async def capture(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
        frames.append(message)

    monkeypatch.setattr(
        import_module("browser_agent.extension.service"), "_write_native_frame", capture
    )
    writer = cast(asyncio.StreamWriter, Writer())
    await service._finish_task(  # pyright: ignore[reportPrivateUsage]
        writer, success=status == "completed", summary="Visible outcome", task_status=status
    )
    await service._send_runtime_snapshot(writer)  # pyright: ignore[reportPrivateUsage]
    result = next(frame for frame in frames if frame["type"] == "runtime.task.result")
    assert cast(dict[str, object], result["payload"])["outcome"] == outcome
    snapshot = cast(dict[str, object], frames[-1]["payload"])
    session = cast(dict[str, object], snapshot["session"])
    assert session["status"] == status
    events = cast(list[dict[str, object]], snapshot["events"])
    assert len(events) == 1
    assert events[0]["runId"] == "managed-run"
    assert events[0]["detail"] == "Visible outcome"
    assert (events[0]["status"] == "completed") == (status == "completed")
