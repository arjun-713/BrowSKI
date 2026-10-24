"""Chrome Native Messaging relay to the owner-only local runtime socket."""

from __future__ import annotations

import io
import os
import select
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

from browser_agent.extension.native_messaging import (
    MAX_NATIVE_HOST_MESSAGE_BYTES,
    MAX_NATIVE_MESSAGE_BYTES,
    NativeMessagingProtocolError,
    read_native_message,
    validate_extension_origin,
    write_native_message,
)

_READ_SIZE = 16 * 1024
_SERVICE_START_SECONDS = 15.0
_SERVICE_POLL_SECONDS = 0.25


class NativeHostError(RuntimeError):
    """Raised when the host cannot establish a safe local relay."""


class NativeFrameBuffer:
    """Incrementally validate and split length-prefixed JSON object frames."""

    def __init__(self, max_bytes: int = MAX_NATIVE_MESSAGE_BYTES) -> None:
        self._max_bytes = max_bytes
        self._buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buffer.extend(data)
        frames: list[bytes] = []

        while len(self._buffer) >= 4:
            length = int.from_bytes(self._buffer[:4], "little")
            if length == 0 or length > self._max_bytes:
                raise NativeMessagingProtocolError("native messaging frame size is outside limits")
            frame_length = 4 + length
            if len(self._buffer) < frame_length:
                break

            frame = bytes(self._buffer[:frame_length])
            message = read_native_message(io.BytesIO(frame), max_bytes=self._max_bytes)
            if message is None:
                raise NativeMessagingProtocolError("native messaging frame is empty")
            frames.append(frame)
            del self._buffer[:frame_length]

        if len(self._buffer) > self._max_bytes + 4:
            raise NativeMessagingProtocolError("native messaging frame size is outside limits")
        return frames

    def finish(self) -> None:
        if self._buffer:
            raise NativeMessagingProtocolError("truncated native messaging frame")


def default_runtime_socket() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "browski" / "bridge.sock"
    return Path.home() / ".local" / "state" / "browski" / "bridge.sock"


def validate_runtime_socket(path: Path) -> None:
    """Require an owner-only socket beneath a private directory."""
    if not path.is_absolute():
        raise NativeHostError("local runtime socket path must be absolute")
    try:
        parent = path.parent.lstat()
        socket_stat = path.lstat()
    except OSError as exc:
        raise NativeHostError("local runtime socket is unavailable") from exc

    current_uid = os.getuid()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != current_uid
        or stat.S_IMODE(parent.st_mode) & 0o077
    ):
        raise NativeHostError("local runtime socket directory permissions are unsafe")
    if not stat.S_ISSOCK(socket_stat.st_mode):
        raise NativeHostError("local runtime endpoint is not a Unix socket")
    if socket_stat.st_uid != current_uid or stat.S_IMODE(socket_stat.st_mode) & 0o077:
        raise NativeHostError("local runtime socket permissions are unsafe")


def read_runtime_token(socket_path: Path) -> str:
    """Read the runtime's owner-only ephemeral host token without logging it."""
    token_path = socket_path.with_suffix(".token")
    try:
        token_stat = token_path.lstat()
        if (
            not stat.S_ISREG(token_stat.st_mode)
            or token_stat.st_uid != os.getuid()
            or stat.S_IMODE(token_stat.st_mode) & 0o077
            or token_stat.st_size > 128
        ):
            raise NativeHostError("local runtime token permissions are unsafe")
        token = token_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise NativeHostError("local runtime authentication token is unavailable") from exc
    if not 32 <= len(token) <= 128:
        raise NativeHostError("local runtime authentication token is invalid")
    return token


def runtime_ready(socket_path: Path) -> bool:
    """True only when a private runtime socket is present and accepting connections.

    A stopped service can leave its socket and token files behind; existence alone
    would skip autostart and leave the panel offline.
    """
    try:
        validate_runtime_socket(socket_path)
        read_runtime_token(socket_path)
    except NativeHostError:
        return False
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(_SERVICE_POLL_SECONDS * 4)
        probe.connect(str(socket_path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def _runtime_working_directory(executable: Path) -> Path:
    """Repository root for a source install (.venv inside python/), else home.

    The service resolves the default Laya checkpoint and the local ``.env``
    relative to its working directory, exactly as when started by hand.
    """
    parents = executable.absolute().parents
    if len(parents) > 3 and (parents[2] / "pyproject.toml").is_file():
        return parents[3]
    return Path.home()


def start_runtime_service(socket_path: Path, *, executable: Path | None = None) -> None:
    """Start ``browski serve`` beside this host and wait a bounded time for it.

    The service's own lock refuses a second instance, so a race between two
    hosts starts at most one runtime.
    """
    interpreter = executable or Path(sys.executable)
    browski = interpreter.with_name("browski")
    if not os.access(browski, os.X_OK):
        raise NativeHostError("the BROWSKI runtime is not installed beside the native host")
    log_dir = Path.home() / ".local" / "state" / "browski"
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_fd = os.open(log_dir / "backend.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        subprocess.Popen(  # noqa: S603 - fixed sibling executable, no shell
            [str(browski), "serve", "--socket-path", str(socket_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_fd,
            stderr=log_fd,
            cwd=_runtime_working_directory(interpreter),
            start_new_session=True,
        )
    finally:
        os.close(log_fd)
    deadline = time.monotonic() + _SERVICE_START_SECONDS
    while time.monotonic() < deadline:
        if runtime_ready(socket_path):
            return
        time.sleep(_SERVICE_POLL_SECONDS)
    raise NativeHostError("the BROWSKI runtime did not start in time")


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise NativeHostError("native messaging output closed")
        offset += written


def relay_native_messages(
    connection: socket.socket,
    *,
    input_fd: int = 0,
    output_fd: int = 1,
) -> None:
    """Relay bounded frames until Chrome or the local runtime disconnects."""
    native_input = NativeFrameBuffer()
    runtime_input = NativeFrameBuffer(MAX_NATIVE_HOST_MESSAGE_BYTES)
    os.set_blocking(input_fd, False)
    connection.settimeout(2.0)

    while True:
        readable, _, _ = select.select([input_fd, connection], [], [])
        if input_fd in readable:
            chunk = os.read(input_fd, _READ_SIZE)
            if not chunk:
                native_input.finish()
                return
            for frame in native_input.feed(chunk):
                connection.sendall(frame)

        if connection in readable:
            chunk = connection.recv(_READ_SIZE)
            if not chunk:
                runtime_input.finish()
                return
            for frame in runtime_input.feed(chunk):
                _write_all(output_fd, frame)


def run_native_host(
    origin: str,
    *,
    extension_id: str,
    socket_path: Path,
) -> None:
    """Authorize Chrome, then relay its protocol to the local runtime."""
    validate_extension_origin(origin, {extension_id})
    if not runtime_ready(socket_path):
        start_runtime_service(socket_path)
    validate_runtime_socket(socket_path)
    token = read_runtime_token(socket_path)

    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.settimeout(2.0)
        connection.connect(str(socket_path))
        connection.settimeout(None)
        authentication = io.BytesIO()
        write_native_message(authentication, {"type": "runtime.auth", "token": token})
        connection.sendall(authentication.getvalue())
        relay_native_messages(connection)
    except OSError as exc:
        raise NativeHostError("could not connect to the local BROWSKI runtime") from exc
    finally:
        connection.close()


def main() -> None:
    """Native Messaging entry point; keep stdout reserved for framed messages."""
    origin = sys.argv[1] if len(sys.argv) == 2 else ""
    extension_id = os.environ.get("BROWSKI_EXTENSION_ID", "")
    if not extension_id:
        print("BROWSKI native host is not configured.", file=sys.stderr)
        raise SystemExit(1)

    try:
        run_native_host(
            origin,
            extension_id=extension_id,
            socket_path=Path(
                os.environ.get("BROWSKI_RUNTIME_SOCKET", str(default_runtime_socket()))
            ),
        )
    except (NativeHostError, NativeMessagingProtocolError):
        print("BROWSKI native host could not establish a valid connection.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
