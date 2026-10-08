"""Private Unix-socket broker between the extension and Rust CDP transport."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import stat
import struct
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from browser_agent.extension.native_messaging import (
    MAX_NATIVE_HOST_MESSAGE_BYTES,
)

PROTOCOL_VERSION = 1
MAX_BACKEND_FRAME_BYTES = 8 * 1024 * 1024
MAX_IN_FLIGHT_COMMANDS = 128
MAX_OWNED_TAB_COUNT = 8
MAX_OWNED_TAB_URL_BYTES = 2048
_HEADER = struct.Struct("<I")
_ATTACHMENT_WAIT_SECONDS = 5
_COMMAND_TIMEOUT_SECONDS = 35
logger = logging.getLogger(__name__)

_CDP_METHODS = frozenset(
    {
        "Accessibility.getFullAXTree",
        "CSS.enable",
        "CSS.getComputedStyleForNode",
        "DOM.enable",
        "DOM.focus",
        "DOM.getBoxModel",
        "DOM.getDocument",
        "DOM.getNodeForLocation",
        "DOM.resolveNode",
        "DOM.scrollIntoViewIfNeeded",
        "Input.dispatchKeyEvent",
        "Input.dispatchMouseEvent",
        "Input.insertText",
        "Page.enable",
        "Page.captureScreenshot",
        "Page.getLayoutMetrics",
        "Page.getNavigationHistory",
        "Page.handleJavaScriptDialog",
        "Page.navigate",
        "Page.navigateToHistoryEntry",
        "Page.reload",
        "Runtime.enable",
        "Runtime.evaluate",
        "Runtime.callFunctionOn",
        "BROWSKI.tabs.create",
        "BROWSKI.tabs.activate",
        "BROWSKI.tabs.close",
        "BROWSKI.tabs.stop",
    }
)
_OWNED_TAB_METHODS = frozenset(
    {
        "BROWSKI.tabs.create",
        "BROWSKI.tabs.activate",
        "BROWSKI.tabs.close",
        "BROWSKI.tabs.stop",
    }
)


class ExtensionBackendError(RuntimeError):
    """Raised when an attached-browser backend connection is invalid."""


@dataclass(frozen=True)
class Attachment:
    attachment_id: str
    tab_id: int
    session_id: str


async def _write_extension_frame(
    writer: asyncio.StreamWriter,
    message: dict[str, object],
) -> None:
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not payload or len(payload) > MAX_NATIVE_HOST_MESSAGE_BYTES:
        raise ExtensionBackendError("extension frame size is outside limits")
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


async def _read_backend_frame(reader: asyncio.StreamReader) -> dict[str, object]:
    header = await reader.readexactly(_HEADER.size)
    (length,) = _HEADER.unpack(header)
    if length == 0 or length > MAX_BACKEND_FRAME_BYTES:
        raise ExtensionBackendError("backend frame size is outside limits")
    value = json.loads(await reader.readexactly(length))
    if not isinstance(value, dict):
        raise ExtensionBackendError("backend frame must contain a JSON object")
    return cast(dict[str, object], value)


async def _write_backend_frame(
    writer: asyncio.StreamWriter,
    message: dict[str, object],
) -> None:
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if not payload or len(payload) > MAX_BACKEND_FRAME_BYTES:
        raise ExtensionBackendError("backend frame size is outside limits")
    writer.write(_HEADER.pack(len(payload)) + payload)
    await writer.drain()


def _valid_opaque_id(value: str, prefix: str) -> bool:
    if not value.startswith(prefix):
        return False
    try:
        identifier = uuid.UUID(value.removeprefix(prefix))
    except (ValueError, AttributeError):
        return False
    return str(identifier) == value.removeprefix(prefix).lower()


def _valid_owned_tab_url(value: str) -> bool:
    if (
        not value
        or len(value.encode("utf-8")) > MAX_OWNED_TAB_URL_BYTES
        or any(
            character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
            for character in value
        )
    ):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _validate_owned_tab_command(
    method: str,
    params: dict[str, object],
    owned_sessions: dict[str, str],
) -> None:
    owned_targets = set(owned_sessions.values())
    root_target = next(
        (target for target in owned_sessions.values() if target.startswith("extension-tab-")),
        None,
    )
    if method == "BROWSKI.tabs.create":
        url = params.get("url")
        if set(params) != {"url"} or not isinstance(url, str) or not _valid_owned_tab_url(url):
            raise ExtensionBackendError("new-tab URL must be a bounded credential-free HTTP(S) URL")
        if len(owned_sessions) >= MAX_OWNED_TAB_COUNT:
            raise ExtensionBackendError("the attachment-owned tab limit has been reached")
    elif method in {"BROWSKI.tabs.activate", "BROWSKI.tabs.close"}:
        target_id = params.get("targetId")
        if (
            set(params) != {"targetId"}
            or not isinstance(target_id, str)
            or target_id not in owned_targets
        ):
            raise ExtensionBackendError("requested tab is not owned by this attachment")
        if method == "BROWSKI.tabs.close" and target_id == root_target:
            raise ExtensionBackendError(
                "the initially attached user tab cannot be closed by the agent"
            )
    elif method == "BROWSKI.tabs.stop":
        if params:
            raise ExtensionBackendError("tab stop accepts no parameters")


class ExtensionCdpBackend:
    """Forward bounded CDP operations for one attachment-owned tab set."""

    def __init__(self, socket_path: Path, token: str) -> None:
        self.socket_path = socket_path
        self._token = token
        self._server: asyncio.AbstractServer | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._extension_writer: asyncio.StreamWriter | None = None
        self._extension_methods: frozenset[str] = frozenset()
        self._extension_events: frozenset[str] = frozenset()
        self._attachment: Attachment | None = None
        self._owned_sessions: dict[str, str] = {}
        self._attachment_ready = asyncio.Event()
        self._backend_writer: asyncio.StreamWriter | None = None
        self._backend_write_lock = asyncio.Lock()
        self._extension_write_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[None]] = {}
        self._pending_methods: dict[int, str] = {}
        self._pending_sessions: dict[int, str] = {}
        self._last_request_id = 0
        self._command_tasks: set[asyncio.Task[None]] = set()
        # The MV3 proxy accepts at most eight outstanding debugger commands.
        # Backpressure here preserves observation completeness during bursts.
        self._command_capacity = asyncio.Semaphore(4)
        self._closed = False

    @property
    def is_connected(self) -> bool:
        return self._backend_writer is not None and not self._backend_writer.is_closing()

    @property
    def attachment(self) -> Attachment | None:
        return self._attachment

    async def start(self) -> None:
        if self._closed:
            raise ExtensionBackendError("a closed backend cannot be restarted")
        if self._server is not None:
            raise ExtensionBackendError("extension CDP backend is already running")
        if not self.socket_path.is_absolute() or len(os.fsencode(self.socket_path)) >= 100:
            raise ExtensionBackendError("backend socket path must be absolute and below 100 bytes")
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ExtensionBackendError("backend socket path is not an owned Unix socket")
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._handle_backend,
            path=self.socket_path,
            limit=MAX_BACKEND_FRAME_BYTES + _HEADER.size,
        )
        metadata = self.socket_path.lstat()
        self._socket_identity = (metadata.st_dev, metadata.st_ino)
        os.chmod(self.socket_path, 0o600, follow_symlinks=False)

    def set_extension_connection(
        self,
        writer: asyncio.StreamWriter,
        *,
        methods: list[str],
        events: list[str],
    ) -> None:
        self._extension_writer = writer
        self._extension_methods = frozenset(methods) & _CDP_METHODS
        self._extension_events = frozenset(events)

    def set_attachment(self, attachment: Attachment) -> None:
        if self._attachment is not None and self._attachment != attachment:
            raise ExtensionBackendError("another browser attachment already owns the backend")
        self._attachment = attachment
        self._owned_sessions = {attachment.session_id: f"extension-tab-{attachment.attachment_id}"}
        self._attachment_ready.set()

    async def detach_attachment(
        self,
        attachment_id: str,
        *,
        notify_browser: bool = True,
    ) -> None:
        attachment = self._attachment
        if attachment is None or attachment.attachment_id != attachment_id:
            return
        try:
            if notify_browser:
                await self._write_backend(
                    {"type": "backend.detached", "reason": "browser tab detached"}
                )
        except (OSError, ExtensionBackendError):
            logger.debug("Attached browser transport was already disconnected")
        finally:
            self._attachment = None
            self._owned_sessions.clear()
            self._attachment_ready.clear()
            self._fail_pending()

    async def handle_extension_message(self, message: dict[str, object]) -> bool:
        message_type = message["type"]
        payload = cast(dict[str, object], message["payload"])
        attachment = self._attachment
        if message_type == "debugger.command.result":
            if attachment is None or not self.is_connected:
                return True
            if payload.get("attachmentId") != attachment.attachment_id:
                raise ExtensionBackendError("debugger response belongs to a different attachment")
            command_id = payload.get("commandId")
            if not isinstance(command_id, str) or not command_id.startswith("browski-"):
                raise ExtensionBackendError("debugger response request ID is invalid")
            try:
                request_id = int(command_id.removeprefix("browski-"))
            except ValueError as error:
                raise ExtensionBackendError("debugger response request ID is invalid") from error
            future = self._pending.get(request_id)
            if future is None:
                return True
            if payload.get("sessionId") != self._pending_sessions.get(request_id):
                raise ExtensionBackendError("debugger response belongs to a different tab session")
            if "error" not in payload:
                result_payload = payload.get("result", {})
                if not isinstance(result_payload, dict):
                    raise ExtensionBackendError("debugger result must be an object")
                result_fields = cast(dict[str, object], result_payload)
                if self._pending_methods.get(request_id) == "BROWSKI.tabs.create":
                    target_id = result_fields.get("targetId")
                    tab_session_id = result_fields.get("tabSessionId")
                    if (
                        not isinstance(target_id, str)
                        or not _valid_opaque_id(target_id, "browser-tab-")
                        or not isinstance(tab_session_id, str)
                        or not _valid_opaque_id(tab_session_id, "browser-session-")
                        or tab_session_id in self._owned_sessions
                        or len(self._owned_sessions) >= MAX_OWNED_TAB_COUNT
                    ):
                        raise ExtensionBackendError("owned-tab creation result is invalid")
                    title = result_fields.get("title", "")
                    url = result_fields.get("url")
                    if (
                        not isinstance(title, str)
                        or len(title) > 512
                        or not isinstance(url, str)
                        or not _valid_owned_tab_url(url)
                    ):
                        raise ExtensionBackendError("owned-tab creation metadata is invalid")
                    self._owned_sessions[tab_session_id] = target_id
            result: dict[str, object] = {
                "type": "backend.response",
                "requestId": request_id,
            }
            if "error" in payload:
                result["error"] = payload["error"]
            else:
                result["result"] = payload.get("result", {})
            await self._write_backend(result)
            if not future.done():
                future.set_result(None)
            return True
        if message_type == "debugger.event":
            if attachment is None or not self.is_connected:
                return True
            if payload.get("attachmentId") != attachment.attachment_id:
                raise ExtensionBackendError("debugger event belongs to a different attachment")
            target_session_id = payload.get("sessionId")
            if (
                not isinstance(target_session_id, str)
                or target_session_id not in self._owned_sessions
            ):
                return True
            method = payload.get("method")
            if not isinstance(method, str) or method not in self._extension_events:
                return True
            params = payload.get("params", {})
            if method == "Target.targetDestroyed":
                params_fields = cast(dict[str, object], params) if isinstance(params, dict) else {}
                target_id = params_fields.get("targetId")
                if (
                    target_session_id == attachment.session_id
                    or not isinstance(target_id, str)
                    or self._owned_sessions.get(target_session_id) != target_id
                ):
                    raise ExtensionBackendError(
                        "target-destroyed event does not match an owned tab"
                    )
                self._owned_sessions.pop(target_session_id, None)
            await self._write_backend(
                {
                    "type": "backend.event",
                    "method": method,
                    "params": params,
                    "sessionId": target_session_id,
                }
            )
            return True
        if message_type == "browser.tab.detached":
            if attachment is not None and payload.get("attachmentId") == attachment.attachment_id:
                await self._write_backend(
                    {
                        "type": "backend.detached",
                        "reason": payload.get("reason", "browser tab detached"),
                    }
                )
                self._attachment = None
                self._owned_sessions.clear()
                self._attachment_ready.clear()
            return True
        return False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        server, self._server = self._server, None
        if server is not None:
            server.close()
            await server.wait_closed()
        writer, self._backend_writer = self._backend_writer, None
        if writer is not None:
            writer.close()
            await writer.wait_closed()
        for task in tuple(self._command_tasks):
            task.cancel()
        if self._command_tasks:
            await asyncio.gather(*self._command_tasks, return_exceptions=True)
        self._fail_pending()
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if self._socket_identity == (metadata.st_dev, metadata.st_ino):
            self.socket_path.unlink(missing_ok=True)
        self._socket_identity = None

    async def _handle_backend(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self._closed or self._backend_writer is not None:
            writer.close()
            await writer.wait_closed()
            return
        self._backend_writer = writer
        try:
            await self._authenticate(reader)
            hello = await asyncio.wait_for(_read_backend_frame(reader), timeout=5)
            await asyncio.wait_for(self._attachment_ready.wait(), timeout=_ATTACHMENT_WAIT_SECONDS)
            current = self._attachment
            payload_value = hello.get("payload")
            payload = (
                cast(dict[str, object], payload_value) if isinstance(payload_value, dict) else None
            )
            if (
                hello.get("type") != "backend.hello"
                or hello.get("protocolVersion") != PROTOCOL_VERSION
                or payload is None
                or current is None
                or payload.get("attachmentId") != current.attachment_id
                or payload.get("sessionId") != current.session_id
                or not self._extension_methods
            ):
                raise ExtensionBackendError(
                    "backend hello does not match the active tab attachment"
                )
            await _write_backend_frame(
                writer,
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "type": "backend.ready",
                },
            )
            while True:
                message = await _read_backend_frame(reader)
                self._validate_backend_message(message, current)
                await self._command_capacity.acquire()
                task = asyncio.create_task(self._dispatch_command(message, current))
                self._command_tasks.add(task)
                task.add_done_callback(self._command_finished)
        except (
            TimeoutError,
            asyncio.IncompleteReadError,
            OSError,
            ValueError,
            TypeError,
            ExtensionBackendError,
        ) as exc:
            logger.info(
                "Attached browser backend connection closed",
                extra={"error_type": type(exc).__name__},
            )
            if isinstance(exc, ExtensionBackendError):
                logger.debug("Backend protocol refusal: %s", exc)
        finally:
            if self._backend_writer is writer:
                self._backend_writer = None
            command_tasks = tuple(self._command_tasks)
            for task in command_tasks:
                task.cancel()
            if command_tasks:
                await asyncio.gather(*command_tasks, return_exceptions=True)
            self._fail_pending()
            self._last_request_id = 0
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    def _command_finished(self, task: asyncio.Task[None]) -> None:
        self._command_tasks.discard(task)
        self._command_capacity.release()
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Attached browser command task failed",
                extra={"error_type": type(error).__name__},
            )
            if self._backend_writer is not None:
                self._backend_writer.close()

    async def _authenticate(self, reader: asyncio.StreamReader) -> None:
        auth = await asyncio.wait_for(_read_backend_frame(reader), timeout=3)
        token = auth.get("token")
        if (
            auth.get("type") != "runtime.auth"
            or auth.get("role") != "browser_backend"
            or not isinstance(token, str)
            or not hmac.compare_digest(token, self._token)
        ):
            raise ExtensionBackendError("backend authentication failed")

    def _validate_backend_message(
        self,
        message: dict[str, object],
        attachment: Attachment,
    ) -> None:
        payload = message.get("payload")
        request_id = message.get("requestId")
        if message.get("type") != "backend.command":
            raise ExtensionBackendError("backend message type is not a command")
        if message.get("protocolVersion") != PROTOCOL_VERSION:
            raise ExtensionBackendError("backend command protocol version is unsupported")
        if type(request_id) is not int or request_id <= self._last_request_id:
            raise ExtensionBackendError("backend command request ID is invalid or replayed")
        if not isinstance(payload, dict):
            raise ExtensionBackendError("backend command payload must be an object")
        fields = cast(dict[str, object], payload)
        if set(fields) != {"attachmentId", "sessionId", "method", "params"}:
            raise ExtensionBackendError("backend command payload fields are invalid")
        if fields.get("attachmentId") != attachment.attachment_id:
            raise ExtensionBackendError("backend command does not match the attached tab")
        session_id = fields.get("sessionId")
        if not isinstance(session_id, str) or session_id not in self._owned_sessions:
            raise ExtensionBackendError("backend command targets an unowned tab session")
        method = fields.get("method")
        if not isinstance(method, str) or not method or len(method) > 128:
            raise ExtensionBackendError("backend command method is invalid")
        if not isinstance(fields.get("params"), dict):
            raise ExtensionBackendError("backend command params must be an object")
        params = cast(dict[str, object], fields["params"])
        if method == "Page.captureScreenshot" and params != {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": False,
        }:
            raise ExtensionBackendError(
                "screenshot parameters exceed the supported viewport capture"
            )
        if method in _OWNED_TAB_METHODS:
            if session_id != attachment.session_id:
                raise ExtensionBackendError(
                    "owned-tab lifecycle commands require the owner session"
                )
            _validate_owned_tab_command(method, params, self._owned_sessions)
        elif method not in self._extension_methods:
            # The later dispatch path will return the same bounded refusal;
            # reject malformed ownership here before allocating a task.
            if session_id != attachment.session_id:
                raise ExtensionBackendError("unsupported command targets a non-root session")
        if len(self._pending) >= MAX_IN_FLIGHT_COMMANDS:
            raise ExtensionBackendError("backend command queue is full")
        self._last_request_id = request_id

    async def _dispatch_command(
        self,
        message: dict[str, object],
        attachment: Attachment,
    ) -> None:
        request_id = cast(int, message["requestId"])
        payload = cast(dict[str, object], message["payload"])
        if payload["method"] not in self._extension_methods:
            # Valid framing does not imply permission. Refuse this request
            # without destroying the browser session used by other commands.
            await self._write_backend(
                {
                    "type": "backend.response",
                    "requestId": request_id,
                    "error": "Unsupported attached-browser capability",
                }
            )
            return
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._pending_methods[request_id] = cast(str, payload["method"])
        self._pending_sessions[request_id] = cast(str, payload["sessionId"])
        command_id = f"browski-{request_id}"
        try:
            await self._send_extension(
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "type": "debugger.command",
                    "eventId": str(uuid.uuid4()),
                    "payload": {
                        "attachmentId": attachment.attachment_id,
                        "sessionId": payload["sessionId"],
                        "commandId": command_id,
                        "method": payload["method"],
                        "params": payload["params"],
                    },
                }
            )
            await asyncio.wait_for(future, timeout=_COMMAND_TIMEOUT_SECONDS)
        except (TimeoutError, OSError, ExtensionBackendError):
            if self.is_connected:
                await self._write_backend(
                    {
                        "type": "backend.response",
                        "requestId": request_id,
                        "error": "extension debugger command timed out or disconnected",
                    }
                )
        finally:
            self._pending.pop(request_id, None)
            self._pending_methods.pop(request_id, None)
            self._pending_sessions.pop(request_id, None)

    async def _send_extension(self, message: dict[str, object]) -> None:
        writer = self._extension_writer
        if writer is None or writer.is_closing():
            raise ExtensionBackendError("extension Native Messaging connection is unavailable")
        async with self._extension_write_lock:
            await _write_extension_frame(writer, message)

    async def _write_backend(self, message: dict[str, object]) -> None:
        writer = self._backend_writer
        if writer is None or writer.is_closing():
            return
        async with self._backend_write_lock:
            await _write_backend_frame(writer, message)

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result(None)
        self._pending_methods.clear()
        self._pending_sessions.clear()
