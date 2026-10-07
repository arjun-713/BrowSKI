"""Native Messaging framing and extension-origin boundary tests."""

from __future__ import annotations

import io
import struct

import pytest

from browser_agent.extension.native_messaging import (
    NativeMessagingProtocolError,
    read_native_message,
    validate_extension_origin,
    write_native_message,
)


def test_native_message_round_trips_unicode_json() -> None:
    message = {"type": "extension.hello", "payload": {"label": "BROWSKI ✓"}}
    stream = io.BytesIO()

    write_native_message(stream, message)
    stream.seek(0)

    assert read_native_message(stream) == message
    assert stream.read() == b""


def test_native_message_returns_none_at_clean_eof() -> None:
    assert read_native_message(io.BytesIO()) is None


def test_native_message_reads_partial_stream_chunks() -> None:
    class ShortReadStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            if size is None or size < 0:
                return super().read(size)
            return super().read(min(size, 2))

    message = {"type": "extension.hello", "payload": {"version": 1}}
    encoded = io.BytesIO()
    write_native_message(encoded, message)

    assert read_native_message(ShortReadStream(encoded.getvalue())) == message


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (b"\x01\x00", "header"),
        (struct.pack("<I", 0), "size"),
        (struct.pack("<I", 3) + b"{}", "payload"),
        (struct.pack("<I", 1_000), "size"),
        (struct.pack("<I", 2) + b"[]", "object"),
        (struct.pack("<I", 1) + b"\xff", "UTF-8 JSON"),
        (struct.pack("<I", 9) + b'{"x":NaN}', "UTF-8 JSON"),
        (struct.pack("<I", 13) + b'{"x":1,"x":2}', "UTF-8 JSON"),
    ],
)
def test_native_message_rejects_invalid_frames(frame: bytes, reason: str) -> None:
    with pytest.raises(NativeMessagingProtocolError, match=reason):
        read_native_message(io.BytesIO(frame), max_bytes=128)


def test_native_message_rejects_non_finite_json_numbers_on_write() -> None:
    with pytest.raises(NativeMessagingProtocolError, match="serializable"):
        write_native_message(io.BytesIO(), {"value": float("nan")})


def test_extension_origin_requires_exact_allowlisted_chrome_origin() -> None:
    allowed = {"a" * 32}

    assert validate_extension_origin("chrome-extension://" + "a" * 32 + "/", allowed) == "a" * 32

    for origin in (
        "https://" + "a" * 32 + "/",
        "chrome-extension://" + "b" * 32 + "/",
        "chrome-extension://" + "a" * 31 + "/",
        "chrome-extension://" + "a" * 31 + "q/",
        "chrome-extension://" + "a" * 32 + "/path",
        "chrome-extension://" + "a" * 32 + "/?query=1",
        "chrome-extension://user@" + "a" * 32 + "/",
    ):
        with pytest.raises(NativeMessagingProtocolError, match="authorized extension"):
            validate_extension_origin(origin, allowed)
