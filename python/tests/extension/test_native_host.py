"""Native host socket and relay behavior tests."""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
from pathlib import Path

import pytest

from browser_agent.extension.native_host import (
    NativeFrameBuffer,
    NativeHostError,
    relay_native_messages,
    validate_runtime_socket,
)


def _frame(message: dict[str, object]) -> bytes:
    payload = json.dumps(message, separators=(",", ":")).encode()
    return struct.pack("<I", len(payload)) + payload


def test_frame_buffer_handles_partial_and_multiple_frames() -> None:
    decoder = NativeFrameBuffer()
    first = _frame({"type": "extension.hello"})
    second = _frame({"type": "runtime.status", "ok": True})

    assert decoder.feed(first[:3]) == []
    assert decoder.feed(first[3:] + second) == [first, second]
    decoder.finish()


def test_frame_buffer_rejects_non_json_payload() -> None:
    decoder = NativeFrameBuffer()
    malformed = struct.pack("<I", 1) + b"x"

    with pytest.raises(ValueError, match="valid UTF-8 JSON"):
        decoder.feed(malformed)


def test_validate_runtime_socket_requires_owner_only_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "bridge.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        socket_path.chmod(0o600)
        validate_runtime_socket(socket_path)

        socket_path.chmod(0o666)
        with pytest.raises(NativeHostError, match="permissions are unsafe"):
            validate_runtime_socket(socket_path)
    finally:
        server.close()


def test_relay_forwards_validated_frames_in_both_directions() -> None:
    native_reader, native_writer = os.pipe()
    output_reader, output_writer = os.pipe()
    host_socket, runtime_socket = socket.socketpair()
    errors: list[BaseException] = []

    def relay() -> None:
        try:
            relay_native_messages(
                host_socket,
                input_fd=native_reader,
                output_fd=output_writer,
            )
        except BaseException as exc:  # surfaced in the test thread
            errors.append(exc)

    worker = threading.Thread(target=relay)
    worker.start()
    try:
        request = _frame({"type": "extension.hello"})
        os.write(native_writer, request)
        assert runtime_socket.recv(len(request)) == request

        response = _frame({"type": "host.hello"})
        runtime_socket.sendall(response)
        received = os.read(output_reader, len(response))
        assert received == response
    finally:
        os.close(native_writer)
        worker.join(timeout=2)
        for fd in (native_reader, output_reader, output_writer):
            os.close(fd)
        host_socket.close()
        runtime_socket.close()

    assert not worker.is_alive()
    assert errors == []
