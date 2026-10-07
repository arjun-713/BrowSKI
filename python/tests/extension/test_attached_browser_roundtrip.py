"""Exercise the Rust browser session through the Python extension broker."""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import cast

import pytest

from browser_agent.extension.backend import Attachment, ExtensionCdpBackend

_HEADER = struct.Struct("<I")
_ENABLE_METHODS = {"Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"}


async def _read_extension_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    (length,) = _HEADER.unpack(await reader.readexactly(_HEADER.size))
    value = json.loads(await reader.readexactly(length))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.asyncio
async def test_python_session_uses_rust_core_over_extension_broker(tmp_path: Path) -> None:
    from browser_agent.session import BrowserSession

    extension_socket = tmp_path / "extension.sock"
    backend_socket = tmp_path / "backend.sock"
    extension_writer_ready: asyncio.Future[asyncio.StreamWriter] = (
        asyncio.get_running_loop().create_future()
    )

    async def accept_extension(
        _reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        extension_writer_ready.set_result(writer)
        await writer.wait_closed()

    extension_server = await asyncio.start_unix_server(
        accept_extension,
        path=extension_socket,
    )
    backend = ExtensionCdpBackend(backend_socket, "roundtrip-token")
    await backend.start()
    extension_reader, extension_client_writer = await asyncio.open_unix_connection(
        str(extension_socket)
    )
    extension_writer = await extension_writer_ready
    backend.set_extension_connection(
        extension_writer,
        methods=sorted(_ENABLE_METHODS),
        events=["Page.loadEventFired"],
    )
    backend.set_attachment(Attachment("attachment-2", 10, "runtime-session-2"))

    session_task = asyncio.create_task(
        BrowserSession.attach_extension(
            socket_path=str(backend_socket),
            token="roundtrip-token",
            attachment_id="attachment-2",
            session_id="runtime-session-2",
            target_id="extension-tab-10",
            title="Attached tab",
            url="https://example.test/",
        )
    )
    session: BrowserSession | None = None
    try:
        received: set[str] = set()
        while received != _ENABLE_METHODS:
            command = await asyncio.wait_for(_read_extension_frame(extension_reader), timeout=5)
            assert command["type"] == "debugger.command"
            payload = cast(dict[str, object], command["payload"])
            method = payload["method"]
            assert isinstance(method, str)
            received.add(method)
            await backend.handle_extension_message(
                {
                    "type": "debugger.command.result",
                    "payload": {
                        "attachmentId": "attachment-2",
                        "sessionId": "runtime-session-2",
                        "commandId": payload["commandId"],
                        "result": {},
                    },
                }
            )
        attached_session = await asyncio.wait_for(session_task, timeout=5)
        session = attached_session
        assert session.session_id == "runtime-session-2"
        assert await session.active_tab_id() == "extension-tab-10"
    finally:
        if session is not None:
            await session.close()
        elif not session_task.done():
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)
        extension_client_writer.close()
        await extension_client_writer.wait_closed()
        extension_writer.close()
        await extension_writer.wait_closed()
        await backend.close()
        extension_server.close()
        await extension_server.wait_closed()
