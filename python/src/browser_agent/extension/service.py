"""Owner-only Unix socket service for the extension Native Messaging relay."""

from __future__ import annotations

import asyncio
import fcntl
import hmac
import logging
import os
import secrets
import stat
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from browser_agent.cli.config import BrowskiConfig, ExecutionEngine, load_config
from browser_agent.credentials import CredentialStore, SystemCredentialStore
from browser_agent.extension.backend import (
    Attachment,
    ExtensionBackendError,
    ExtensionCdpBackend,
)
from browser_agent.extension.diagnostics import (
    DiagnosticRequest,
    DiagnosticResponse,
    inspect_attached_runtime,
)
from browser_agent.extension.native_messaging import (
    MAX_NATIVE_MESSAGE_BYTES,
)
from browser_agent.extension.protocol import (
    DEBUGGER_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    ExtensionMessageValidator,
    ExtensionProtocolError,
)
from browser_agent.extension.settings_service import ExtensionSettingsService
from browser_agent.extension.wire import HEADER as _HEADER
from browser_agent.extension.wire import read_native_frame as _read_native_frame
from browser_agent.extension.wire import write_native_frame as _write_native_frame
from browser_agent.telemetry.debug_log import DebugRecorder, record_debug

if TYPE_CHECKING:
    from browser_agent.engines.contracts import EngineEvent
    from browser_agent.engines.lifecycle import ActionApproval, TaskControl
    from browser_agent.session import BrowserSession

logger = logging.getLogger(__name__)

_AUTH_TIMEOUT_SECONDS = 3
_HELLO_TIMEOUT_SECONDS = 5
_MESSAGE_TIMEOUT_SECONDS = 300


class BridgeServiceError(RuntimeError):
    """Raised when the local extension bridge cannot start or serve safely."""


def default_socket_path() -> Path:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "browski" / "bridge.sock"
    return Path.home() / ".local" / "state" / "browski" / "bridge.sock"


class ExtensionBridgeService:
    """Serve authenticated, versioned extension connections over Unix sockets.

    Native Messaging is the extension-facing channel. A second owner-only
    Unix socket carries only authenticated CDP traffic between this service
    and Rust's shared browser core.
    """

    def __init__(
        self,
        socket_path: Path | None = None,
        *,
        config_path: Path | None = None,
        database_path: Path = Path("browski-checkpoints.sqlite"),
        credential_store: CredentialStore | None = None,
        managed_headless: bool = False,
    ) -> None:
        self.socket_path = (socket_path or default_socket_path()).expanduser()
        self.config_path = config_path
        self.database_path = database_path.expanduser()
        self._managed_headless = managed_headless
        self._settings_service = ExtensionSettingsService(
            config_path=self.config_path,
            credential_store=credential_store or SystemCredentialStore(),
            write_frame=_write_native_frame,
        )
        self.token_path = self.socket_path.with_suffix(".token")
        self.lock_path = self.socket_path.with_suffix(".lock")
        self.backend_socket_path = self.socket_path.with_suffix(".backend.sock")
        self._server: asyncio.AbstractServer | None = None
        self._backend: ExtensionCdpBackend | None = None
        self._socket_identity: tuple[int, int] | None = None
        self._lock_fd: int | None = None
        self._token: str | None = None
        self._active_connection = False
        self._writers: set[asyncio.StreamWriter] = set()
        self._extension_writer: asyncio.StreamWriter | None = None
        self._negotiated_methods: list[str] = []
        self._negotiated_events: list[str] = []
        self._runtime_session: dict[str, object] | None = None
        self._timeline_events: list[dict[str, object]] = []
        self._pending_approval: dict[str, object] | None = None
        self._browser_session: object | None = None
        self._attachment_task: asyncio.Task[None] | None = None
        self._attachment_started = asyncio.Event()
        self._task_task: asyncio.Task[None] | None = None
        self._agent_runtime: object | None = None
        self._engine_control: TaskControl | None = None
        self._runtime_context: object | None = None
        self._run_id: str | None = None
        self._request_id: str | None = None
        self._task_label: str | None = None
        self._pending_approval_id: str | None = None
        self._runtime_suspended = False
        self._closed = False
        self._diagnostic_task: asyncio.Task[DiagnosticResponse] | None = None
        self._diagnostic_request_ids: set[str] = set()

    @property
    def runtime_session(self) -> dict[str, object] | None:
        """Return a copy of the currently attached browser session summary."""
        return dict(self._runtime_session) if self._runtime_session is not None else None

    async def wait_for_attached_browser(
        self, *, wait_seconds: float | None = None
    ) -> BrowserSession | None:
        """Wait for initialization, optionally allowing an attach message to arrive.

        With no timeout, inspect the current attachment as before. A bounded
        timeout also waits for a newly dispatched extension attach request.
        A caller timeout must not cancel the service-owned initialization task.
        """
        if wait_seconds is not None and not 0 < wait_seconds <= 30:
            raise ValueError("attachment wait timeout must be in (0, 30] seconds")
        try:
            async with asyncio.timeout(wait_seconds):
                if wait_seconds is not None and self._attachment_task is None and not self._closed:
                    await self._attachment_started.wait()
                task = self._attachment_task
                if task is not None:
                    await asyncio.shield(task)
                return cast(Any, self._browser_session)
        except TimeoutError:
            return None

    async def start(self) -> None:
        """Create the private socket endpoint and start accepting one client."""
        if self._closed:
            raise BridgeServiceError("a closed extension bridge cannot be restarted")
        if self._server is not None:
            raise BridgeServiceError("extension bridge is already running")
        if not self.socket_path.is_absolute():
            raise BridgeServiceError("runtime socket path must be absolute")
        if len(os.fsencode(self.socket_path)) >= 100:
            raise BridgeServiceError("runtime socket path is too long for Unix sockets")

        directory = self.socket_path.parent
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._validate_directory(directory)
            self._acquire_lock()
            self._remove_stale_socket()
            self._remove_stale_token()
            self._token = secrets.token_urlsafe(32)
            self._write_token(self._token)
            self._backend = ExtensionCdpBackend(self.backend_socket_path, self._token)
            await self._backend.start()
            self._server = await asyncio.start_unix_server(
                self._handle_connection,
                path=self.socket_path,
                limit=MAX_NATIVE_MESSAGE_BYTES + _HEADER.size,
            )
            socket_stat = self.socket_path.lstat()
            self._socket_identity = (socket_stat.st_dev, socket_stat.st_ino)
            os.chmod(self.socket_path, 0o600, follow_symlinks=False)
        except (BridgeServiceError, OSError, ValueError) as exc:
            await self.close()
            raise BridgeServiceError("could not create the private extension socket") from exc

    async def serve_forever(self) -> None:
        """Run until cancelled, then remove only this service's socket files."""
        if self._server is None:
            await self.start()
        await self.wait_closed()

    async def wait_closed(self) -> None:
        """Wait on an already-started service and clean up on cancellation."""
        server = self._server
        if server is None:
            raise BridgeServiceError("extension bridge failed to start")
        try:
            async with server:
                await server.serve_forever()
        finally:
            await self.close()

    async def close(self) -> None:
        """Stop accepting clients and remove this service's private endpoint."""
        if self._closed:
            return
        self._closed = True
        diagnostic_task = self._diagnostic_task
        if diagnostic_task is not None and not diagnostic_task.done():
            # Cancelling to_thread does not stop Rust. Close the transport first
            # so outstanding native commands settle before releasing ownership.
            if self._backend is not None:
                await self._backend.close()
            await asyncio.gather(diagnostic_task, return_exceptions=True)
        self._attachment_started.set()
        task_task, self._task_task = self._task_task, None
        if task_task is not None and not task_task.done():
            task_task.cancel()
            await asyncio.gather(task_task, return_exceptions=True)
        await self._close_runtime_context()
        attach_task, self._attachment_task = self._attachment_task, None
        if attach_task is not None and not attach_task.done():
            attach_task.cancel()
            await asyncio.gather(attach_task, return_exceptions=True)
        browser_session, self._browser_session = self._browser_session, None
        if browser_session is not None:
            await cast(Any, browser_session).close()
        server, self._server = self._server, None
        backend, self._backend = self._backend, None
        if backend is not None:
            await backend.close()
        if server is not None:
            server.close()
            for writer in tuple(self._writers):
                writer.close()
            if self._writers:
                await asyncio.gather(
                    *(writer.wait_closed() for writer in tuple(self._writers)),
                    return_exceptions=True,
                )
            await server.wait_closed()
        try:
            self._unlink_owned_socket()
            self._unlink_owned_token()
        finally:
            self._release_lock()

    def _validate_directory(self, directory: Path) -> None:
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise BridgeServiceError("runtime socket directory must be user-owned with mode 0700")

    def _acquire_lock(self) -> None:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.lock_path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            os.close(descriptor)
            raise BridgeServiceError("runtime lock file has unsafe ownership or permissions")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise BridgeServiceError("another BROWSKI runtime is already listening") from exc
        self._lock_fd = descriptor

    def _release_lock(self) -> None:
        descriptor, self._lock_fd = self._lock_fd, None
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _remove_stale_socket(self) -> None:
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise BridgeServiceError("runtime socket path is not an owned Unix socket")

        self.socket_path.unlink()

    def _remove_stale_token(self) -> None:
        try:
            metadata = self.token_path.lstat()
        except FileNotFoundError:
            return
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise BridgeServiceError("runtime token path has unsafe ownership or permissions")
        self.token_path.unlink()

    def _write_token(self, token: str) -> None:
        temporary_path = self.token_path.with_name(f".{self.token_path.name}.{uuid.uuid4().hex}")
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(token)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.token_path)
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        if self._closed or len(self._writers) >= 16 or self._token is None:
            writer.close()
            await writer.wait_closed()
            return
        self._writers.add(writer)
        try:
            await self._authenticate(reader)
            hello_value = await asyncio.wait_for(
                _read_native_frame(reader), timeout=_HELLO_TIMEOUT_SECONDS
            )
            if hello_value.get("type") == "runtime.diagnostics":
                request = DiagnosticRequest.model_validate(hello_value)
                request_id = request.validated_id()
                if request_id in self._diagnostic_request_ids:
                    raise ExtensionProtocolError("diagnostic request was already processed")
                if len(self._diagnostic_request_ids) >= 256:
                    raise ExtensionProtocolError(
                        "diagnostic request budget reached; restart runtime"
                    )
                self._diagnostic_request_ids.add(request_id)
                if self._diagnostic_task is not None and not self._diagnostic_task.done():
                    raise ExtensionProtocolError("a diagnostic probe is already running")
                self._diagnostic_task = asyncio.create_task(
                    self._probe_attached_browser(request_id), name="browski-readonly-diagnostics"
                )
                response = await asyncio.shield(self._diagnostic_task)
                await _write_native_frame(writer, response.model_dump())
            elif not self._active_connection:
                self._active_connection = True
                await self._serve_extension(reader, writer, hello_value)
        except (TimeoutError, asyncio.IncompleteReadError, OSError, ValueError) as exc:
            logger.info("Local bridge client closed", extra={"error_type": type(exc).__name__})
        finally:
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _probe_attached_browser(self, request_id: str) -> DiagnosticResponse:
        browser = cast("BrowserSession | None", self._browser_session)
        if self._runtime_session is None:
            browser = None
        return await inspect_attached_runtime(
            request_id=request_id,
            browser=browser,
            extension_connected=self._extension_writer is not None,
            run_owns_browser=self._runtime_suspended
            or (self._task_task is not None and not self._task_task.done()),
            config_path=self.config_path,
            database_path=self.database_path,
        )

    async def _serve_extension(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        hello_value: dict[str, object],
    ) -> None:
        phase = "handshake"
        try:
            validator = ExtensionMessageValidator()
            hello = validator.validate(hello_value)
            if hello.get("type") != "extension.hello":
                raise ExtensionProtocolError("extension hello must be the first message")
            hello_payload = cast(dict[str, object], hello["payload"])
            methods = cast(list[str], hello_payload["debuggerMethods"])
            events = cast(list[str], hello_payload["debuggerEvents"])
            self._negotiated_methods = methods
            self._negotiated_events = events
            self._extension_writer = writer
            if self._backend is not None:
                self._backend.set_extension_connection(writer, methods=methods, events=events)
            self._configure_idle_engine_session(load_config(self.config_path))
            await self._send_host_hello(writer, methods, events)
            await self._send_runtime_snapshot(writer)
            await self._settings_service.send_credentials_status(writer)

            phase = "connected"
            while True:
                value = await asyncio.wait_for(
                    _read_native_frame(reader), timeout=_MESSAGE_TIMEOUT_SECONDS
                )
                message = validator.validate(value)
                await self._handle_message(writer, message)
        except (
            TimeoutError,
            asyncio.IncompleteReadError,
            OSError,
            ValueError,
            ExtensionBackendError,
        ) as exc:
            logger.info(
                "Extension bridge connection closed",
                extra={"phase": phase, "error_type": type(exc).__name__},
            )
        finally:
            attachment = self._backend.attachment if self._backend is not None else None
            if attachment is not None and self._backend is not None:
                await self._backend.detach_attachment(attachment.attachment_id)
            attach_task, self._attachment_task = self._attachment_task, None
            self._attachment_started.clear()
            if attach_task is not None and not attach_task.done():
                attach_task.cancel()
                await asyncio.gather(attach_task, return_exceptions=True)
            await self._cancel_task()
            browser_session, self._browser_session = self._browser_session, None
            if browser_session is not None:
                await cast(Any, browser_session).close()
            self._runtime_session = None
            if self._extension_writer is writer:
                self._extension_writer = None
            self._active_connection = False

    async def _authenticate(self, reader: asyncio.StreamReader) -> None:
        value = await asyncio.wait_for(_read_native_frame(reader), timeout=_AUTH_TIMEOUT_SECONDS)
        token = value.get("token")
        if (
            value.get("type") != "runtime.auth"
            or not isinstance(token, str)
            or self._token is None
            or not hmac.compare_digest(token, self._token)
        ):
            raise ExtensionProtocolError("local runtime authentication failed")

    async def _handle_message(
        self,
        writer: asyncio.StreamWriter,
        message: dict[str, object],
    ) -> None:
        message_type = message["type"]
        if message_type == "runtime.snapshot.request":
            await self._send_runtime_snapshot(writer)
        elif message_type == "browser.tab.attached":
            if self._has_active_task():
                raise ExtensionProtocolError(
                    "finish the active task before attaching another browser"
                )
            payload_value = message["payload"]
            if isinstance(payload_value, dict):
                payload = cast(dict[str, object], payload_value)
                attachment = Attachment(
                    attachment_id=cast(str, payload["attachmentId"]),
                    tab_id=cast(int, payload["tabId"]),
                    session_id=cast(str, payload["sessionId"]),
                )
                if self._backend is None:
                    raise ExtensionProtocolError("attached-browser backend is unavailable")
                self._backend.set_attachment(attachment)
                self._reset_task_state()
                self._timeline_events = []
                self._pending_approval = None
                self._runtime_session = {
                    "sessionId": attachment.session_id,
                    "updatedAt": datetime.now(UTC).isoformat(),
                    "status": "idle",
                }
                await self._send_runtime_snapshot(writer)
                self._attachment_task = asyncio.create_task(
                    self._open_attached_browser(writer, attachment)
                )
                self._attachment_started.set()
        elif message_type in {
            "debugger.command.result",
            "debugger.event",
            "browser.tab.detached",
        }:
            if self._backend is not None:
                await self._backend.handle_extension_message(message)
            if message_type == "browser.tab.detached":
                attach_task, self._attachment_task = self._attachment_task, None
                self._attachment_started.clear()
                if attach_task is not None and not attach_task.done():
                    attach_task.cancel()
                    await asyncio.gather(attach_task, return_exceptions=True)
                browser_session, self._browser_session = self._browser_session, None
                if browser_session is not None:
                    await cast(Any, browser_session).close()
                if (
                    not self._runtime_session
                    or self._runtime_session.get("browserMode") != "managed"
                ):
                    self._runtime_session = None
                    await self._cancel_task()
                await self._send_runtime_snapshot(writer)
        elif message_type == "runtime.task.submit":
            payload = cast(dict[str, object], message["payload"])
            if self._diagnostic_task is not None and not self._diagnostic_task.done():
                raise ExtensionProtocolError("wait for the read-only browser diagnostic to finish")
            config = load_config(self.config_path)
            managed = config.agent.engine is not ExecutionEngine.LEGACY
            if managed:
                self._configure_idle_engine_session(config)
            if self._runtime_session is None or (
                not managed and (self._backend is None or self._backend.attachment is None)
            ):
                raise ExtensionProtocolError("attach a browser tab before starting a legacy task")
            if payload.get("sessionId") != self._runtime_session.get("sessionId"):
                raise ExtensionProtocolError("task belongs to a different browser session")
            if self._task_task is not None and not self._task_task.done():
                raise ExtensionProtocolError("a browser task is already running")
            if self._runtime_suspended:
                raise ExtensionProtocolError("resume or stop the suspended task first")
            self._task_label = cast(str, payload["task"])[:160]
            self._run_id = str(uuid.uuid4())
            self._request_id = cast(str, message["eventId"])
            recorder = DebugRecorder(load_config(self.config_path).debug)
            with recorder.bind(self._run_id, cast(str, self._runtime_session["sessionId"])):
                record_debug(
                    "task.received",
                    {
                        "prompt": payload["task"],
                        "source": "extension",
                        "request_id": self._request_id,
                        "trace_id": self._run_id,
                        "tab_id": (
                            self._backend.attachment.tab_id
                            if self._backend and self._backend.attachment
                            else None
                        ),
                    },
                )
            self._pending_approval_id = None
            self._pending_approval = None
            self._timeline_events = []
            self._runtime_session["taskLabel"] = self._task_label
            self._runtime_session["runId"] = self._run_id
            self._runtime_session["status"] = "running"
            self._runtime_session["updatedAt"] = datetime.now(UTC).isoformat()
            if managed:
                from browser_agent.engines.lifecycle import TaskControl

                async def events(event: EngineEvent) -> None:
                    await self._send_managed_event(writer, event)

                async def approvals(request: ActionApproval | None) -> None:
                    await self._send_managed_approval(writer, request)

                self._engine_control = TaskControl(
                    config.agent.engine.value,
                    cast(str, self._runtime_session["provider"]),
                    events,
                    approvals=approvals,
                )
            self._task_task = asyncio.create_task(
                self._run_managed_task(writer, payload, self._run_id, config)
                if managed
                else self._run_attached_task(writer, cast(str, payload["task"]), self._run_id),
                name=f"browski-run-{self._run_id}",
            )
            await self._send_runtime_status(writer)
        elif message_type == "runtime.approval.respond":
            payload = cast(dict[str, object], message["payload"])
            if (
                self._runtime_session is None
                or payload.get("sessionId") != self._runtime_session.get("sessionId")
                or payload.get("approvalId") != self._pending_approval_id
                or self._run_id is None
                or (self._agent_runtime is None and self._engine_control is None)
            ):
                raise ExtensionProtocolError("approval does not match the pending browser action")
            approval_id = cast(str, self._pending_approval_id)
            approved = payload.get("decision") == "approve"
            if self._engine_control is not None:
                if not self._engine_control.respond_to_approval(approval_id, approved):
                    raise ExtensionProtocolError("approval is no longer pending")
                # The waiting engine owns cleanup/status and resumes the same
                # task. Never create a second executor for a managed approval.
                return
            await self._send_approval_cleared(writer, approval_id)
            self._pending_approval_id = None
            self._runtime_suspended = False
            self._pending_approval = None
            self._runtime_session["status"] = "running"
            self._task_task = asyncio.create_task(
                self._resume_attached_task(writer, self._run_id, approved),
                name=f"browski-resume-{self._run_id}",
            )
            await self._send_runtime_status(writer)
        elif message_type == "runtime.task.control":
            payload = cast(dict[str, object], message["payload"])
            if self._engine_control is not None:
                if (
                    self._runtime_session is None
                    or payload.get("sessionId") != self._runtime_session.get("sessionId")
                    or payload.get("runId") != self._run_id
                ):
                    raise ExtensionProtocolError(
                        "task control does not match the active engine run"
                    )
                control = payload.get("control")
                if control == "pause":
                    self._engine_control.pause()
                elif control == "resume":
                    self._engine_control.resume()
                else:
                    self._engine_control.stop()
                return
            if (
                self._runtime_session is None
                or payload.get("sessionId") != self._runtime_session.get("sessionId")
                or payload.get("runId") != self._run_id
                or self._agent_runtime is None
                or self._run_id is None
            ):
                raise ExtensionProtocolError("task control does not match the active run")
            control = cast(str, payload["control"])
            if control == "pause":
                if self._task_task is None or self._task_task.done():
                    raise ExtensionProtocolError("the task is already at a safe pause point")
                cast(Any, self._agent_runtime).pause(self._run_id)
            elif control == "resume":
                if not self._runtime_suspended or self._pending_approval_id is not None:
                    raise ExtensionProtocolError("the task is not waiting for a normal resume")
                self._runtime_suspended = False
                self._runtime_session["status"] = "running"
                self._task_task = asyncio.create_task(
                    self._resume_attached_task(writer, self._run_id, None),
                    name=f"browski-resume-{self._run_id}",
                )
            else:
                self._runtime_suspended = False
                if self._task_task is not None and not self._task_task.done():
                    # Keep ownership of the active graph task. Stop requests
                    # cancellation at its safe boundary; it reports completion.
                    await self._stop_attached_task(writer, self._run_id)
                else:
                    await self._stop_attached_task(writer, self._run_id)
            await self._send_runtime_status(writer)
        elif message_type in {
            "runtime.credentials.set",
            "runtime.credentials.clear",
            "runtime.credentials.status.request",
            "runtime.settings.get",
            "runtime.settings.update",
        }:
            handled = await self._settings_service.handle_message(
                writer,
                cast(str, message_type),
                message["payload"],
                active_task=self._has_active_task(),
            )
            if not handled:
                raise ExtensionProtocolError("settings service did not handle a supported message")
            if message_type == "runtime.settings.update" and not self._has_active_task():
                self._configure_idle_engine_session(load_config(self.config_path))
                await self._send_runtime_snapshot(writer)
        elif message_type == "browser.event.dropped":
            return
        else:
            raise ExtensionProtocolError("runtime backend is not available for this message")

    def _reset_task_state(self) -> None:
        self._run_id = None
        self._request_id = None
        self._task_label = None
        self._pending_approval_id = None
        self._runtime_suspended = False
        self._pending_approval = None
        self._agent_runtime = None
        self._runtime_context = None
        self._task_task = None

    async def _cancel_task(self) -> None:
        if self._engine_control is not None:
            self._engine_control.stop()
        task, self._task_task = self._task_task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._close_runtime_context()
        self._agent_runtime = None
        self._engine_control = None
        self._run_id = None
        self._pending_approval_id = None
        self._pending_approval = None

    async def _open_attached_browser(
        self,
        writer: asyncio.StreamWriter,
        attachment: Attachment,
    ) -> None:
        try:
            from browser_agent.cli.config import load_config
            from browser_agent.session import BrowserSession

            config = load_config(self.config_path)

            browser_session = await BrowserSession.attach_extension(
                socket_path=str(self.backend_socket_path),
                token=self._token or "",
                attachment_id=attachment.attachment_id,
                session_id=attachment.session_id,
                target_id=f"extension-tab-{attachment.attachment_id}",
                title="Attached browser tab",
                url="about:blank",
                browser_code_enabled=config.browser_code.enabled,
            )
            if (
                self._closed
                or self._attachment_task is None
                or self._backend is None
                or self._backend.attachment != attachment
            ):
                await browser_session.close()
                return
            self._browser_session = browser_session
        except asyncio.CancelledError:
            raise
        except Exception:
            task = asyncio.current_task()
            if self._attachment_task is task:
                self._attachment_task = None
            self._browser_session = None
            self._runtime_session = None
            backend = self._backend
            if backend is not None:
                try:
                    await backend.detach_attachment(
                        attachment.attachment_id,
                        notify_browser=False,
                    )
                except Exception:
                    logger.debug("Could not clear failed attached browser ownership")
            try:
                if not writer.is_closing():
                    try:
                        await self._send_detach(
                            writer,
                            attachment.attachment_id,
                            "BROWSKI could not initialize the attached browser session.",
                        )
                    except Exception:
                        logger.debug("Could not report attached browser initialization failure")
                if not writer.is_closing():
                    try:
                        await self._send_runtime_snapshot(writer)
                    except Exception:
                        logger.debug("Could not publish attached browser cleanup state")
            finally:
                if backend is not None and backend.attachment is not None:
                    try:
                        await backend.detach_attachment(
                            attachment.attachment_id,
                            notify_browser=False,
                        )
                    except Exception:
                        logger.debug("Could not clear failed attached browser ownership")

    def _configure_idle_engine_session(self, config: BrowskiConfig) -> None:
        if self._task_task is not None and not self._task_task.done():
            return
        if config.agent.engine is ExecutionEngine.LEGACY:
            if self._runtime_session and self._runtime_session.get("browserMode") == "managed":
                self._runtime_session = None
            elif self._backend is None or self._backend.attachment is None:
                self._runtime_session = None
            return
        provider = (
            config.agent.fast_provider.value
            if config.agent.engine is ExecutionEngine.FAST
            else config.agent.text_provider.value
        )
        if self._runtime_session is None:
            self._runtime_session = {
                "sessionId": str(uuid.uuid4()),
                "status": "idle",
                "updatedAt": datetime.now(UTC).isoformat(),
            }
        self._runtime_session.update(
            engine=config.agent.engine.value,
            provider=provider,
            browserMode="managed",
        )

    async def _send_managed_event(self, writer: asyncio.StreamWriter, event: EngineEvent) -> None:
        from browser_agent.extension.engine_tasks import timeline_payload

        session = self._runtime_session
        if session is None or self._run_id is None:
            return
        if event.kind in {"task_paused", "task_resumed"}:
            session["status"] = "paused" if event.kind == "task_paused" else "running"
            await self._send_runtime_status(writer)
        value = timeline_payload(
            event,
            session_id=cast(str, session["sessionId"]),
            run_id=self._run_id,
            sequence=max((cast(int, item["sequence"]) for item in self._timeline_events), default=0)
            + 1,
            request_id=self._request_id,
        )
        if value is not None:
            await self._send_timeline(writer, value)

    async def _send_managed_approval(
        self, writer: asyncio.StreamWriter, request: ActionApproval | None
    ) -> None:
        session = self._runtime_session
        if session is None or self._run_id is None:
            return
        if request is None:
            approval_id = self._pending_approval_id
            self._pending_approval_id = None
            if approval_id is not None:
                await self._send_approval_cleared(writer, approval_id)
            session["status"] = "running"
        else:
            self._pending_approval_id = request.approval_id
            session["status"] = "awaiting_approval"
            await self._send_approval_required(
                writer,
                request.approval_id,
                cast(str, session["sessionId"]),
                {
                    "action": request.action,
                    "target": request.target,
                    "reason": "each new General form interaction requires approval",
                },
            )
        await self._send_runtime_status(writer)

    async def _run_managed_task(
        self,
        writer: asyncio.StreamWriter,
        payload: dict[str, object],
        run_id: str,
        config: BrowskiConfig,
    ) -> None:
        from browser_agent.engines.contracts import CompletionCriteria, EngineStatus
        from browser_agent.engines.product import EngineConfigurationError, execute_managed_task
        from browser_agent.extension.engine_tasks import result_summary

        control = self._engine_control
        if self._runtime_session is None or control is None:
            return
        try:
            verification = payload.get("verification")
            criteria = (
                CompletionCriteria.model_validate(verification)
                if verification is not None
                else None
            )
            start_url = cast(str | None, payload.get("startUrl"))
            result = await execute_managed_task(
                cast(str, payload["task"]),
                config,
                start_url=start_url,
                criteria=criteria,
                events=lambda event: self._send_managed_event(writer, event),
                control=control,
                headless=self._managed_headless,
                run_id=run_id,
                session_id=cast(str, self._runtime_session["sessionId"]),
            )
            summary = result_summary(result)
            await self._finish_task(
                writer,
                success=result.status is EngineStatus.COMPLETED,
                task_status=result.status.value,
                summary=summary or result.status.value,
            )
        except asyncio.CancelledError:
            raise
        except EngineConfigurationError as error:
            await self._finish_task(
                writer, success=False, task_status="blocked", summary=str(error)
            )
        except Exception as error:
            await self._report_task_failure(writer, error)
        finally:
            if self._engine_control is control:
                self._engine_control = None

    async def _run_attached_task(
        self,
        writer: asyncio.StreamWriter,
        task: str,
        run_id: str,
    ) -> None:
        context = None
        try:
            browser = await self.wait_for_attached_browser()
            if browser is None:
                await self._finish_task(
                    writer,
                    success=False,
                    summary="The attached browser is unavailable. Reattach the tab.",
                )
                return
            from browser_agent.agent import AgentRuntime, LunaDecisionAgent
            from browser_agent.cli.config import DecisionMode
            from browser_agent.cli.main import (
                create_luna_reasoning_provider,
                create_luna_vision_provider,
            )
            from browser_agent.decisions import DecisionConfig as LayaConfig
            from browser_agent.decisions import create_decision_provider
            from browser_agent.decisions.config import DecisionProviderName

            config = load_config(self.config_path)
            shadow_provider = None
            if (
                config.decision.mode == DecisionMode.SHADOW
                and config.decision.shadow_telemetry
                and config.privacy.mode.value == "standard"
            ):
                shadow_provider = create_decision_provider(
                    LayaConfig(
                        provider=DecisionProviderName.LAYA,
                        laya_endpoint=config.decision.laya_endpoint,
                    )
                )
            agent = LunaDecisionAgent(
                shadow_provider,
                create_luna_reasoning_provider(config),
                model=config.reasoning.model,
                vision_provider=create_luna_vision_provider(config),
                screenshot_capture=browser.capture_viewport_screenshot,
                browser_code_enabled=config.browser_code.enabled,
                default_effort=config.reasoning.effort,
                site_aliases=config.site_aliases,
            )

            async def event_sink(event: object) -> None:
                payload = cast(Any, event).to_protocol_payload()
                await self._send_timeline(writer, payload)

            context = AgentRuntime.open_sqlite(
                agent,
                browser,
                database=self.database_path,
                event_sink=event_sink,
                debug_config=config.debug,
                session_id=cast(str, (self._runtime_session or {})["sessionId"]),
                request_id=self._request_id,
            )
            runtime = await context.__aenter__()
            self._agent_runtime = runtime
            self._runtime_context = context
            result = await runtime.run(task, run_id=run_id)
            await self._handle_task_result(writer, result)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Attached browser task failed safely")
            await self._report_task_failure(writer, error)
        finally:
            if context is not None and not self._runtime_suspended:
                await context.__aexit__(None, None, None)
                self._agent_runtime = None
                self._runtime_context = None

    async def _resume_attached_task(
        self,
        writer: asyncio.StreamWriter,
        run_id: str,
        approved: bool | None,
    ) -> None:
        runtime = self._agent_runtime
        if runtime is None:
            return
        try:
            if approved is None:
                result = await cast(Any, runtime).resume(run_id)
            else:
                result = await cast(Any, runtime).resume_with_confirmation(
                    run_id,
                    approved=approved,
                )
            await self._handle_task_result(writer, result)
            if not self._runtime_suspended:
                await self._close_runtime_context()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Attached browser task could not resume safely")
            await self._report_task_failure(writer, error)
            await self._close_runtime_context()

    async def _stop_attached_task(self, writer: asyncio.StreamWriter, run_id: str) -> None:
        runtime = self._agent_runtime
        if runtime is None:
            return
        graph_task = self._task_task
        try:
            result = await cast(Any, runtime).stop(run_id)
            if result.status == "running" and graph_task is not None:
                await graph_task
                if (self._runtime_session or {}).get("status") == "stopped":
                    await self._detach_stopped_browser()
                return
            if graph_task is not None and not graph_task.done():
                await graph_task
                if (self._runtime_session or {}).get("status") == "stopped":
                    await self._detach_stopped_browser()
                return
            await self._handle_task_result(writer, result)
            await self._close_runtime_context()
            if result.status == "stopped":
                await self._detach_stopped_browser()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("Attached browser task could not stop safely")
            await self._finish_task(
                writer,
                success=False,
                summary="The task could not stop safely.",
            )
            await self._close_runtime_context()

    async def _detach_stopped_browser(self) -> None:
        """Detach the stopped run's owned debuggers while leaving Chrome open."""
        browser_session, self._browser_session = self._browser_session, None
        self._runtime_session = None
        backend = self._backend
        attachment = backend.attachment if backend is not None else None
        try:
            if browser_session is not None:
                await cast(Any, browser_session).close()
        finally:
            if backend is not None and attachment is not None:
                await backend.detach_attachment(
                    attachment.attachment_id,
                    notify_browser=False,
                )

    async def _close_runtime_context(self) -> None:
        context, self._runtime_context = self._runtime_context, None
        if context is not None:
            await cast(Any, context).__aexit__(None, None, None)
        self._agent_runtime = None

    async def _handle_task_result(self, writer: asyncio.StreamWriter, result: object) -> None:
        state = cast(Any, result)
        status = state.status
        if status == "pending_confirmation":
            session_id = cast(str, (self._runtime_session or {}).get("sessionId", ""))
            approval_id = self._run_id or str(uuid.uuid4())
            details: dict[str, str] = {}
            if self._agent_runtime is not None and self._run_id is not None:
                try:
                    details = await cast(Any, self._agent_runtime).pending_confirmation_details(
                        self._run_id
                    )
                except Exception:
                    logger.error("Could not summarize pending confirmation safely")
            self._pending_approval_id = approval_id
            self._runtime_suspended = True
            self._runtime_session["status"] = "awaiting_approval"  # type: ignore[index]
            await self._send_approval_required(
                writer,
                approval_id,
                session_id,
                details,
            )
            await self._send_runtime_status(writer)
            return
        if status == "paused":
            self._runtime_suspended = True
            self._runtime_session["status"] = "paused"  # type: ignore[index]
            await self._send_runtime_status(writer)
            return
        self._runtime_suspended = False
        await self._finish_task(
            writer,
            success=status == "completed",
            stopped=status == "stopped",
            summary=state.result_summary
            or ("Task completed." if status == "completed" else "Task stopped."),
        )

    async def _report_task_failure(
        self,
        writer: asyncio.StreamWriter,
        error: Exception,
    ) -> None:
        from browser_agent.agent.events import RuntimeEvent, RuntimeEventType, SafeFailureEnvelope

        failure = next(
            (
                cast(dict[str, object], event["failure"])
                for event in reversed(self._timeline_events)
                if event.get("runId") == self._run_id
                and event.get("type") == "RunFailed"
                and isinstance(event.get("failure"), dict)
            ),
            None,
        )
        if failure is None:
            envelope = SafeFailureEnvelope.from_exception(error)
            failure = dict(envelope.to_protocol_payload())
            session_id = cast(str, (self._runtime_session or {}).get("sessionId", "unavailable"))
            event = RuntimeEvent.create(
                session_id=session_id,
                run_id=self._run_id or str(uuid.uuid4()),
                sequence=max(
                    (cast(int, item["sequence"]) for item in self._timeline_events), default=0
                )
                + 1,
                step=0,
                event_type=RuntimeEventType.RUN_FAILED,
                status="failed",
                failure=envelope,
                request_id=self._request_id,
            )
            await self._send_timeline(writer, event.to_protocol_payload())
        await self._finish_task(
            writer,
            success=False,
            summary=cast(str, failure["safeMessage"]),
            failure=failure,
        )

    async def _finish_task(
        self,
        writer: asyncio.StreamWriter,
        *,
        success: bool,
        summary: str,
        stopped: bool = False,
        failure: Mapping[str, object] | None = None,
        task_status: str | None = None,
    ) -> None:
        session = self._runtime_session
        if session is None or writer.is_closing():
            return
        session_id = cast(str, session["sessionId"])
        status = "failed"
        outcome = "failed"
        if success:
            status = "completed"
            outcome = "verified_success"
        elif stopped:
            status = "stopped"
            outcome = "stopped"
        if not success and task_status in {"partially_completed", "blocked", "cancelled"}:
            status = task_status
            outcome = task_status
        if session.get("browserMode") == "managed" and self._run_id is not None:
            terminal = {
                "completed": ("RunCompleted", "Task completed"),
                "partially_completed": ("RunPartiallyCompleted", "Task partially completed"),
                "blocked": ("RunBlocked", "Task blocked"),
                "cancelled": ("RunCancelled", "Task cancelled"),
                "failed": ("RunFailed", "Task failed"),
            }
            kind, label = terminal[status]
            await self._send_timeline(
                writer,
                {
                    "eventId": str(uuid.uuid4()),
                    "sessionId": session_id,
                    "runId": self._run_id,
                    "sequence": max(
                        (cast(int, e["sequence"]) for e in self._timeline_events), default=0
                    )
                    + 1,
                    "step": max(
                        (cast(int, e.get("step", 0)) for e in self._timeline_events), default=0
                    ),
                    "createdAt": datetime.now(UTC).isoformat(),
                    "type": kind,
                    "label": label,
                    "detail": summary[:2_000],
                    "status": "completed"
                    if success
                    else "failed"
                    if status == "failed"
                    else "info",
                    **({"requestId": self._request_id} if self._request_id else {}),
                },
            )
        session["status"] = status
        session["updatedAt"] = datetime.now(UTC).isoformat()
        await self._send_runtime_status(writer)
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.task.result",
                "eventId": str(uuid.uuid4()),
                "payload": {
                    "sessionId": session_id,
                    **({"runId": self._run_id} if self._run_id is not None else {}),
                    "outcome": outcome,
                    "summary": summary[:2_000],
                    "finishedAt": datetime.now(UTC).isoformat(),
                    **({"failure": dict(failure)} if failure is not None else {}),
                },
            },
        )
        self._run_id = None
        self._request_id = None
        self._pending_approval_id = None
        self._pending_approval = None

    async def _send_runtime_status(self, writer: asyncio.StreamWriter) -> None:
        if self._runtime_session is None:
            return
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.status",
                "eventId": str(uuid.uuid4()),
                "payload": {"session": self._runtime_session},
            },
        )

    async def _send_timeline(self, writer: asyncio.StreamWriter, event: dict[str, object]) -> None:
        if writer.is_closing():
            return
        if event.get("type") == "RunFailed" and isinstance(event.get("failure"), dict):
            failure = cast(dict[str, object], event["failure"])
            event["detail"] = failure.get("safeMessage", "The browser task failed.")
        self._timeline_events.append(dict(event))
        self._timeline_events = self._timeline_events[-200:]
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.timeline",
                "eventId": str(uuid.uuid4()),
                "payload": {"event": event},
            },
        )

    async def _send_approval_required(
        self,
        writer: asyncio.StreamWriter,
        approval_id: str,
        session_id: str,
        details: dict[str, str],
    ) -> None:
        action = details.get("action", "high-risk action")
        target = details.get("target", "the browser page")
        reason = details.get("reason", "the action may have a consequential effect")
        approval: dict[str, object] = {
            "approvalId": approval_id,
            "sessionId": session_id,
            "title": f"Confirm {action}"[:160],
            "summary": (
                f"Target: {target}. Reason: {reason}. Review the browser page before approving."
            )[:500],
            "risk": "high",
        }
        self._pending_approval = approval
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.approval.required",
                "eventId": str(uuid.uuid4()),
                "payload": {"approval": approval},
            },
        )

    async def _send_approval_cleared(self, writer: asyncio.StreamWriter, approval_id: str) -> None:
        self._pending_approval = None
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.approval.cleared",
                "eventId": str(uuid.uuid4()),
                "payload": {"approvalId": approval_id},
            },
        )

    def _has_active_task(self) -> bool:
        if self._task_task is not None and not self._task_task.done():
            return True
        if self._runtime_suspended:
            return True
        return bool(
            self._runtime_session
            and self._runtime_session.get("status") in {"running", "paused", "awaiting_approval"}
        )

    async def _send_host_hello(
        self,
        writer: asyncio.StreamWriter,
        methods: list[str],
        events: list[str],
    ) -> None:
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "host.hello",
                "eventId": str(uuid.uuid4()),
                "payload": {
                    "supportedProtocolVersions": [PROTOCOL_VERSION],
                    "debuggerProtocolVersion": DEBUGGER_PROTOCOL_VERSION,
                    "debuggerMethods": methods,
                    "debuggerEvents": events,
                },
            },
        )

    async def _send_runtime_snapshot(self, writer: asyncio.StreamWriter) -> None:
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "runtime.snapshot",
                "eventId": str(uuid.uuid4()),
                "payload": {
                    "session": self._runtime_session,
                    "events": self._timeline_events[-200:],
                    "pendingApproval": self._pending_approval,
                },
            },
        )

    async def _send_detach(
        self,
        writer: asyncio.StreamWriter,
        attachment_id: str,
        reason: str,
    ) -> None:
        await _write_native_frame(
            writer,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "type": "debugger.detach",
                "eventId": str(uuid.uuid4()),
                "payload": {
                    "attachmentId": attachment_id,
                    "reason": reason,
                },
            },
        )

    def _unlink_owned_socket(self) -> None:
        if self._socket_identity is None:
            return
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if (metadata.st_dev, metadata.st_ino) == self._socket_identity:
            self.socket_path.unlink(missing_ok=True)
        self._socket_identity = None

    def _unlink_owned_token(self) -> None:
        if self._token is None:
            return
        try:
            token = self.token_path.read_text(encoding="ascii")
        except (OSError, UnicodeError):
            return
        if hmac.compare_digest(token, self._token):
            self.token_path.unlink(missing_ok=True)
        self._token = None
