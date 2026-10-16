"""Check that native browser failures cross PyO3 with safe metadata."""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import Any, cast

import pytest

from browser_agent.extension.backend import Attachment, ExtensionCdpBackend
from browser_agent.session import BrowserSession

_HEADER = struct.Struct("<I")
_ATTACH_METHODS = {"Page.enable", "DOM.enable", "CSS.enable", "Runtime.enable"}


async def _read_extension_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    (length,) = _HEADER.unpack(await reader.readexactly(_HEADER.size))
    value = json.loads(await reader.readexactly(length))
    assert isinstance(value, dict)
    return cast(dict[str, object], value)


@pytest.mark.asyncio
async def test_closed_observation_error_has_safe_native_metadata(tmp_path: Path) -> None:
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
    backend = ExtensionCdpBackend(backend_socket, "native-error-token")
    await backend.start()
    extension_reader, extension_client_writer = await asyncio.open_unix_connection(
        str(extension_socket)
    )
    extension_writer = await extension_writer_ready
    backend.set_extension_connection(
        extension_writer,
        methods=sorted(_ATTACH_METHODS | {"Page.getLayoutMetrics", "Runtime.evaluate"}),
        events=[],
    )
    backend.set_attachment(Attachment("native-error-attachment", 12, "native-error-session"))

    session_task = asyncio.create_task(
        BrowserSession.attach_extension(
            socket_path=str(backend_socket),
            token="native-error-token",
            attachment_id="native-error-attachment",
            session_id="native-error-session",
            target_id="extension-tab-12",
            title="Attached tab",
            url="https://example.test/",
        )
    )
    session: BrowserSession | None = None
    try:
        attached_methods: set[str] = set()
        while attached_methods != _ATTACH_METHODS:
            command = await asyncio.wait_for(
                _read_extension_frame(extension_reader),
                timeout=5,
            )
            payload = cast(dict[str, object], command["payload"])
            method = cast(str, payload["method"])
            attached_methods.add(method)
            await backend.handle_extension_message(
                {
                    "type": "debugger.command.result",
                    "payload": {
                        "attachmentId": "native-error-attachment",
                        "sessionId": "native-error-session",
                        "commandId": payload["commandId"],
                        "result": {},
                    },
                }
            )

        session = await asyncio.wait_for(session_task, timeout=5)
        native = cast(Any, session)._native
        probe_task = asyncio.create_task(asyncio.to_thread(native.probe_connection))
        probe_command = await asyncio.wait_for(
            _read_extension_frame(extension_reader),
            timeout=5,
        )
        probe_payload = cast(dict[str, object], probe_command["payload"])
        assert probe_payload["method"] == "Page.getLayoutMetrics"
        await backend.handle_extension_message(
            {
                "type": "debugger.command.result",
                "payload": {
                    "attachmentId": "native-error-attachment",
                    "sessionId": "native-error-session",
                    "commandId": probe_payload["commandId"],
                    "result": {"layoutViewport": {}},
                },
            }
        )
        await asyncio.wait_for(probe_task, timeout=5)

        await asyncio.to_thread(native.close)
        with pytest.raises(RuntimeError) as caught:
            await asyncio.to_thread(native.observe_json)

        error = caught.value
        assert getattr(error, "component", None) == "browser_core"
        assert getattr(error, "operation", None) == "observe"
        assert getattr(error, "native_error_type", None) == "SESSION_CLOSED"
        assert getattr(error, "failure_kind", None) == "EXECUTION"
        assert getattr(error, "recoverable", None) is False
        assert "closed" in str(error)
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
