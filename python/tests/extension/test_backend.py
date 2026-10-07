"""Authenticated Rust-to-extension CDP broker tests."""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import cast

import pytest

from browser_agent.extension.backend import Attachment, ExtensionCdpBackend

_HEADER = struct.Struct("<I")


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
