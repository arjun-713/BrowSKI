"""Authenticated Rust-to-extension CDP broker tests."""

# These tests deliberately exercise the broker's internal framing and pending
# request maps to verify rejection behavior at its trust boundary.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import cast

import pytest

from browser_agent.extension.backend import (
    Attachment,
    ExtensionBackendError,
    ExtensionCdpBackend,
)

_HEADER = struct.Struct("<I")


@pytest.mark.asyncio
async def test_detach_clears_backend_ownership_after_rust_transport_resets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ExtensionCdpBackend(tmp_path / "unused.sock", "token")
    backend.set_attachment(Attachment("attach-1", 7, "session-1"))

    async def write_reset(_message: dict[str, object]) -> None:
        raise ConnectionResetError("transport closed")

    monkeypatch.setattr(backend, "_write_backend", write_reset)

    await backend.detach_attachment("attach-1")

    assert backend.attachment is None
    assert backend._owned_sessions == {}
    assert not backend._attachment_ready.is_set()


def test_owned_tab_commands_require_bounded_urls_and_owned_targets(tmp_path: Path) -> None:
    backend = ExtensionCdpBackend(tmp_path / "unused.sock", "token")
    backend.set_attachment(Attachment("attach-1", 7, "session-1"))
    backend._extension_methods = frozenset({"Page.enable", "Page.captureScreenshot"})

    attachment = backend.attachment
    assert attachment is not None

    def validate(session_id: str, method: str, params: dict[str, object]) -> None:
        backend._validate_backend_message(
            {
                "type": "backend.command",
                "protocolVersion": 1,
                "requestId": backend._last_request_id + 1,
                "payload": {
                    "attachmentId": "attach-1",
                    "sessionId": session_id,
                    "method": method,
                    "params": params,
                },
            },
            attachment,
        )

    validate("session-1", "BROWSKI.tabs.create", {"url": "https://example.test/"})
    validate("session-1", "Page.enable", {})
    with pytest.raises(ExtensionBackendError, match="credential-free"):
        validate("session-1", "BROWSKI.tabs.create", {"url": "https://user:secret@example.test/"})
    with pytest.raises(ExtensionBackendError, match=r"credential-free HTTP\(S\)"):
        validate("session-1", "BROWSKI.tabs.create", {"url": "file:///tmp/private"})
    with pytest.raises(ExtensionBackendError, match="screenshot parameters"):
        validate("session-1", "Page.captureScreenshot", {"format": "png", "clip": {}})
    with pytest.raises(ExtensionBackendError, match="unowned tab session"):
        validate("not-owned", "Page.enable", {})


@pytest.mark.asyncio
async def test_owned_tab_session_routes_only_after_valid_creation_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = ExtensionCdpBackend(tmp_path / "unused.sock", "token")
    backend.set_attachment(Attachment("attach-1", 7, "session-1"))
    monkeypatch.setattr(ExtensionCdpBackend, "is_connected", property(lambda _backend: True))
    backend._pending[1] = asyncio.get_running_loop().create_future()
    backend._pending_methods[1] = "BROWSKI.tabs.create"
    backend._pending_sessions[1] = "session-1"
    handled = await backend.handle_extension_message(
        {
            "type": "debugger.command.result",
            "payload": {
                "attachmentId": "attach-1",
                "sessionId": "session-1",
                "commandId": "browski-1",
                "result": {
                    "targetId": "browser-tab-123e4567-e89b-12d3-a456-426614174000",
                    "tabSessionId": "browser-session-123e4567-e89b-12d3-a456-426614174001",
                    "title": "Example",
                    "url": "https://example.test/",
                },
            },
        }
    )
    assert handled is True
    assert backend._owned_sessions["browser-session-123e4567-e89b-12d3-a456-426614174001"] == (
        "browser-tab-123e4567-e89b-12d3-a456-426614174000"
    )
    backend._fail_pending()


async def _read_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    (length,) = _HEADER.unpack(await reader.readexactly(_HEADER.size))
    value = json.loads(await reader.readexactly(length))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


async def _write_frame(writer: asyncio.StreamWriter, value: dict[str, object]) -> None:
    payload = json.dumps(value, separators=(",", ":")).encode()
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


@pytest.mark.asyncio
async def test_backend_authenticates_attachment_and_relays_command_response_and_event(
    tmp_path: Path,
) -> None:
    extension_socket = tmp_path / "extension.sock"
    backend_socket = tmp_path / "backend.sock"
    extension_ready: asyncio.Future[asyncio.StreamWriter] = (
        asyncio.get_running_loop().create_future()
    )

    async def accept_extension(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        extension_ready.set_result(writer)
        await writer.wait_closed()

    extension_server = await asyncio.start_unix_server(
        accept_extension,
        path=extension_socket,
    )
    backend = ExtensionCdpBackend(backend_socket, "private-test-token")
    await backend.start()
    extension_reader, extension_client_writer = await asyncio.open_unix_connection(
        str(extension_socket)
    )
    extension_writer = await extension_ready
    backend.set_extension_connection(
        extension_writer,
        methods=["Page.enable"],
        events=["Page.loadEventFired"],
    )
    attachment = Attachment("attach-1", 7, "session-1")
    backend.set_attachment(attachment)

    rust_reader, rust_writer = await asyncio.open_unix_connection(str(backend_socket))
    try:
        await _write_frame(
            rust_writer,
            {
                "type": "runtime.auth",
                "role": "browser_backend",
                "token": "private-test-token",
            },
        )
        await _write_frame(
            rust_writer,
            {
                "protocolVersion": 1,
                "type": "backend.hello",
                "payload": {"attachmentId": "attach-1", "sessionId": "session-1"},
            },
        )
        assert (await _read_frame(rust_reader))["type"] == "backend.ready"

        await _write_frame(
            rust_writer,
            {
                "protocolVersion": 1,
                "type": "backend.command",
                "requestId": 10,
                "payload": {
                    "attachmentId": "attach-1",
                    "sessionId": "session-1",
                    "method": "Network.setCookie",
                    "params": {},
                },
            },
        )
        refused = await asyncio.wait_for(_read_frame(rust_reader), timeout=2)
        assert refused["requestId"] == 10
        assert "error" in refused

        await _write_frame(
            rust_writer,
            {
                "protocolVersion": 1,
                "type": "backend.command",
                "requestId": 11,
                "payload": {
                    "attachmentId": "attach-1",
                    "sessionId": "session-1",
                    "method": "Page.enable",
                    "params": {},
                },
            },
        )
        command = await asyncio.wait_for(_read_frame(extension_reader), timeout=2)
        assert command["type"] == "debugger.command"
        command_payload = command["payload"]
        assert isinstance(command_payload, dict)
        assert command_payload["commandId"] == "browski-11"

        await backend.handle_extension_message(
            {
                "type": "debugger.command.result",
                "payload": {
                    "attachmentId": "attach-1",
                    "sessionId": "session-1",
                    "commandId": "browski-11",
                    "result": {"enabled": True},
                },
            }
        )
        response = await asyncio.wait_for(_read_frame(rust_reader), timeout=2)
        assert response == {
            "type": "backend.response",
            "requestId": 11,
            "result": {"enabled": True},
        }

        await backend.handle_extension_message(
            {
                "type": "debugger.event",
                "payload": {
                    "attachmentId": "attach-1",
                    "sessionId": "session-1",
                    "sequence": 3,
                    "method": "Page.loadEventFired",
                    "params": {"timestamp": 1.5},
                },
            }
        )
        event = await asyncio.wait_for(_read_frame(rust_reader), timeout=2)
        assert event["type"] == "backend.event"
        assert event["method"] == "Page.loadEventFired"
        assert event["sessionId"] == "session-1"

        # Observation can issue many commands together. The broker must
        # queue them before Chrome's eight-command proxy ceiling is reached.
        for request_id in range(20, 52):
            await _write_frame(
                rust_writer,
                {
                    "protocolVersion": 1,
                    "type": "backend.command",
                    "requestId": request_id,
                    "payload": {
                        "attachmentId": "attach-1",
                        "sessionId": "session-1",
                        "method": "Page.enable",
                        "params": {},
                    },
                },
            )
        queued = [
            await asyncio.wait_for(_read_frame(extension_reader), timeout=2) for _ in range(4)
        ]
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_read_frame(extension_reader), timeout=0.05)
        answered: set[int] = set()
        for index in range(32):
            command = (
                queued[index]
                if index < len(queued)
                else await asyncio.wait_for(_read_frame(extension_reader), timeout=2)
            )
            command_payload = cast(dict[str, object], command["payload"])
            await backend.handle_extension_message(
                {
                    "type": "debugger.command.result",
                    "payload": {
                        "attachmentId": "attach-1",
                        "sessionId": "session-1",
                        "commandId": command_payload["commandId"],
                        "result": {},
                    },
                }
            )
            response = await asyncio.wait_for(_read_frame(rust_reader), timeout=2)
            assert "error" not in response
            answered.add(cast(int, response["requestId"]))
        assert answered == set(range(20, 52))
    finally:
        rust_writer.close()
        await rust_writer.wait_closed()
        extension_client_writer.close()
        await extension_client_writer.wait_closed()
        extension_writer.close()
        await extension_writer.wait_closed()
        await backend.close()
        extension_server.close()
        await extension_server.wait_closed()
