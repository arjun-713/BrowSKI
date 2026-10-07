"""Browser extension host integration and transport primitives."""

from browser_agent.extension.native_messaging import (
    MAX_NATIVE_MESSAGE_BYTES,
    NativeMessagingProtocolError,
    read_native_message,
    validate_extension_origin,
    write_native_message,
)

__all__ = [
    "MAX_NATIVE_MESSAGE_BYTES",
    "NativeMessagingProtocolError",
    "read_native_message",
    "validate_extension_origin",
    "write_native_message",
]
