"""Bounded Chrome Native Messaging framing and origin validation."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from typing import BinaryIO, cast
from urllib.parse import urlsplit

MAX_NATIVE_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_NATIVE_HOST_MESSAGE_BYTES = 1_048_576
_HEADER = struct.Struct("<I")


class NativeMessagingProtocolError(ValueError):
    """Raised when a native messaging frame is malformed or oversized."""


def read_native_message(
    stream: BinaryIO,
    *,
    max_bytes: int = MAX_NATIVE_MESSAGE_BYTES,
) -> dict[str, object] | None:
    """Read one little-endian length-prefixed JSON object, or EOF between frames."""
    if not 1 <= max_bytes <= 64 * 1024 * 1024:
        raise ValueError("native messaging frame limit must be between 1 byte and 64 MiB")

    first_header_byte = stream.read(1)
    if first_header_byte == b"":
        return None
    header = first_header_byte + _read_exact(
        stream,
        _HEADER.size - 1,
        component="header",
    )

    (length,) = _HEADER.unpack(header)
    if length == 0 or length > max_bytes:
        raise NativeMessagingProtocolError("native messaging frame size is outside limits")

    payload = _read_exact(stream, length)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise NativeMessagingProtocolError(
            "native messaging payload is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise NativeMessagingProtocolError("native messaging payload must be a JSON object")
    return cast(dict[str, object], value)


def write_native_message(
    stream: BinaryIO,
    message: Mapping[str, object],
    *,
    max_bytes: int = MAX_NATIVE_HOST_MESSAGE_BYTES,
) -> None:
    """Write one bounded JSON object using Chrome's native messaging framing."""
    if not 1 <= max_bytes <= 1_048_576:
        raise ValueError("native messaging host output must be between 1 byte and 1 MiB")
    try:
        payload = json.dumps(
            dict(message),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NativeMessagingProtocolError(
            "native messaging message is not JSON serializable"
        ) from exc
    if not payload or len(payload) > max_bytes:
        raise NativeMessagingProtocolError("native messaging frame size is outside limits")
    stream.write(_HEADER.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def validate_extension_origin(origin: str, allowed_extension_ids: set[str]) -> str:
    """Return the authorized extension ID or reject any non-exact Chrome origin."""
    parsed = urlsplit(origin)
    extension_id = parsed.netloc
    has_chrome_extension_id_shape = len(extension_id) == 32 and all(
        "a" <= character <= "p" for character in extension_id
    )
    if (
        parsed.scheme != "chrome-extension"
        or not has_chrome_extension_id_shape
        or parsed.path != "/"
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or extension_id not in allowed_extension_ids
    ):
        raise NativeMessagingProtocolError("native host caller is not an authorized extension")
    return extension_id


def _read_exact(
    stream: BinaryIO,
    length: int,
    *,
    component: str = "payload",
) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise NativeMessagingProtocolError(f"truncated native messaging frame {component}")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant {value!r}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result
