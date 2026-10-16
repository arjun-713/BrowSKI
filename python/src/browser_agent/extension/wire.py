"""Async Native Messaging framing shared by the local service and diagnostics."""

from __future__ import annotations

import asyncio
import io
import struct

from browser_agent.extension.native_messaging import (
    MAX_NATIVE_MESSAGE_BYTES,
    NativeMessagingProtocolError,
    read_native_message,
    write_native_message,
)

HEADER = struct.Struct("<I")
WRITE_TIMEOUT_SECONDS = 5


async def read_native_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    header = await reader.readexactly(HEADER.size)
    (length,) = HEADER.unpack(header)
    if length == 0 or length > MAX_NATIVE_MESSAGE_BYTES:
        raise NativeMessagingProtocolError("native messaging frame size is outside limits")
    payload = await reader.readexactly(length)
    message = read_native_message(io.BytesIO(header + payload))
    if message is None:
        raise NativeMessagingProtocolError("native messaging frame is empty")
    return message


async def write_native_frame(writer: asyncio.StreamWriter, message: dict[str, object]) -> None:
    buffer = io.BytesIO()
    write_native_message(buffer, message)
    writer.write(buffer.getvalue())
    await asyncio.wait_for(writer.drain(), timeout=WRITE_TIMEOUT_SECONDS)
