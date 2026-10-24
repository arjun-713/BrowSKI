"""Loopback CDP relay that lets Browser Use drive the user's own Chrome tabs (ADR-032).

Browser Use expects a browser-level CDP WebSocket. An extension only has
per-tab ``chrome.debugger``. This relay hosts two loopback endpoints per lease:

- ``/devtools/browser/<token>`` for exactly one Browser Use client;
- ``/extension/<token>`` for exactly one extension service-worker connection.

It emulates the small browser-level ``Target``/``Browser`` surface Browser Use
uses over the leased tabs only, and forwards per-tab commands to the extension.
Numeric Chrome tab IDs never reach Browser Use; it sees synthetic target IDs.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any, cast

logger = logging.getLogger(__name__)

MAX_FRAME_BYTES = 64 * 1024 * 1024
EXTENSION_CONNECT_SECONDS = 15.0
COMMAND_TIMEOUT_SECONDS = 60.0
MAX_IN_FLIGHT_COMMANDS = 64
MAX_LEASED_TABS = 12

# Session-level domains/methods the agent must never reach in the user's browser.
_REFUSED_DOMAINS = ("Browser.", "Storage.", "SystemInfo.", "Tracing.", "IO.", "Fetch.")
_REFUSED_METHODS = frozenset(
    {
        "Network.getCookies",
        "Network.getAllCookies",
        "Network.setCookie",
        "Network.setCookies",
        "Network.deleteCookies",
        "Network.clearBrowserCookies",
        "Network.clearBrowserCache",
        "Page.setDownloadBehavior",
        "Target.createTarget",
        "Target.closeTarget",
        "Target.createBrowserContext",
        "Target.disposeBrowserContext",
        "Target.exposeDevToolsProtocol",
        "Target.setDiscoverTargets",
        "Target.setRemoteLocations",
    }
)


class RelayError(RuntimeError):
    """Safe, user-presentable relay failure."""


class _Raw(str):
    """CDP JSON forwarded verbatim: big snapshots are never parsed or re-encoded here."""


# Large CDP payloads (DOM, accessibility, snapshots: often 10+ MB per capture)
# travel as "<kind> <small JSON header>\n<raw JSON body>". Only the header is
# parsed; the body is spliced into the reply for Browser Use unchanged.
_RAW_RESULT = "R "
_RAW_EVENT = "E "
# Events the relay must read to keep its session map current.
_PARSED_EVENTS = frozenset({"Target.attachedToTarget", "Target.detachedFromTarget"})


class _CdpError(Exception):
    def __init__(self, message: str, code: int = -32000) -> None:
        super().__init__(message)
        self.code = code


def session_method_allowed(method: str) -> bool:
    """Relay policy for per-tab commands; mirrored by the extension."""
    return not method.startswith(_REFUSED_DOMAINS) and method not in _REFUSED_METHODS


@dataclass
class _Tab:
    tab_id: int
    target_id: str
    url: str
    title: str
    created_by_agent: bool
    page_session: str | None = None
    child_sessions: set[str] = field(default_factory=set[str])

    def target_info(self) -> dict[str, object]:
        return {
            "targetId": self.target_id,
            "type": "page",
            "title": self.title,
            "url": self.url,
            "attached": self.page_session is not None,
            "canAccessOpener": False,
            "browserContextId": "BROWSKI",
        }


@dataclass
class RelayLease:
    """One task's access to the user's browser through the relay."""

    cdp_url: str
    cancelled: asyncio.Event
    cancel_reason: str | None = None


Notify = Callable[[str, dict[str, object]], Awaitable[None]]


class AgentRelay:
    """Create one relay lease at a time; the service supplies the native-message sender."""

    def __init__(self, notify: Notify) -> None:
        self._notify = notify
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    @contextlib.asynccontextmanager
    async def lease(self) -> AsyncGenerator[RelayLease]:
        if self._active:
            raise RelayError("Another task is already using the browser.")
        self._active = True
        lease_id = str(uuid.uuid4())
        state = _RelayState()
        try:
            async with state.serve() as port:
                extension_url = f"ws://127.0.0.1:{port}/extension/{state.extension_token}"
                await self._notify("relay.open", {"leaseId": lease_id, "url": extension_url})
                try:
                    await state.wait_ready()
                    lease = RelayLease(
                        cdp_url=f"ws://127.0.0.1:{port}/devtools/browser/{state.browser_token}",
                        cancelled=state.cancelled,
                    )
                    state.lease = lease
                    yield lease
                finally:
                    await state.shutdown()
                    with contextlib.suppress(Exception):
                        await self._notify("relay.close", {"leaseId": lease_id})
        finally:
            self._active = False


class _RelayState:
    """Per-lease connections, ID mapping and pending commands."""

    def __init__(self) -> None:
        self.browser_token = secrets.token_urlsafe(32)
        self.extension_token = secrets.token_urlsafe(32)
        self.cancelled = asyncio.Event()
        self.lease: RelayLease | None = None
        self._ready = asyncio.Event()
        self._failure: str | None = None
        self._extension: Any = None
        self._client: Any = None
        self._tabs: dict[int, _Tab] = {}
        self._sessions: dict[str, tuple[int, str | None]] = {}
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._discover = False
        self._auto_attach = False
        self._slots = asyncio.Semaphore(MAX_IN_FLIGHT_COMMANDS)
        self._send_lock = asyncio.Lock()

    # ---- server lifecycle -------------------------------------------------

    @contextlib.asynccontextmanager
    async def serve(self) -> AsyncGenerator[int]:
        from websockets.asyncio.server import serve

        async with serve(
            self._route,
            "127.0.0.1",
            0,
            max_size=MAX_FRAME_BYTES,
            # Loopback only: compressing multi-megabyte DOM payloads costs far
            # more CPU than it could ever save in transfer time.
            compression=None,
            process_request=self._check_path,
            ping_interval=20,
            ping_timeout=60,
        ) as server:
            yield cast(int, next(iter(server.sockets)).getsockname()[1])

    def _check_path(self, connection: Any, request: Any) -> Any:
        if request.path in {self._browser_path, self._extension_path}:
            return None
        return connection.respond(HTTPStatus.NOT_FOUND, "Not found\n")

    @property
    def _browser_path(self) -> str:
        return f"/devtools/browser/{self.browser_token}"

    @property
    def _extension_path(self) -> str:
        return f"/extension/{self.extension_token}"

    async def _route(self, connection: Any) -> None:
        path = connection.request.path
        if path == self._extension_path and self._extension is None:
            self._extension = connection
            await self._serve_extension(connection)
        elif path == self._browser_path and self._client is None and self._ready.is_set():
            self._client = connection
            await self._serve_client(connection)
        else:
            await connection.close(code=1008, reason="connection refused")

    async def wait_ready(self) -> None:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=EXTENSION_CONNECT_SECONDS)
        except TimeoutError as error:
            raise RelayError(
                "The browser extension did not connect. Reload the BROWSKI extension and retry."
            ) from error
        if self._failure is not None:
            raise RelayError(self._failure)

    async def shutdown(self) -> None:
        self._fail_pending("The browser relay closed.")
        if self._extension is not None:
            with contextlib.suppress(Exception):
                await self._extension.send(json.dumps({"type": "close"}))
            with contextlib.suppress(Exception):
                await self._extension.close()
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.close()

    def _cancel(self, reason: str) -> None:
        if self.lease is not None and self.lease.cancel_reason is None:
            self.lease.cancel_reason = reason
        self.cancelled.set()

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(_CdpError(reason))
        self._pending.clear()

    # ---- extension side ---------------------------------------------------

    async def _serve_extension(self, connection: Any) -> None:
        try:
            async for raw in connection:
                if isinstance(raw, bytes):
                    continue
                if raw.startswith((_RAW_RESULT, _RAW_EVENT)):
                    await self._on_raw_frame(raw)
                else:
                    await self._on_extension_message(json.loads(raw))
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as error:
            logger.warning("Rejected malformed relay frame", extra={"error": type(error).__name__})
        finally:
            if not self._ready.is_set():
                self._failure = "The browser extension closed the relay before it was ready."
                self._ready.set()
            self._cancel("The browser extension disconnected.")
            self._fail_pending("The browser extension disconnected.")
            if self._client is not None:
                with contextlib.suppress(Exception):
                    await self._client.close()

    async def _on_extension_message(self, message: dict[str, Any]) -> None:
        kind = message["type"]
        if kind == "ready":
            for tab in message["tabs"]:
                self._add_tab(tab, created_by_agent=bool(tab.get("createdByAgent")))
            self._ready.set()
        elif kind == "failed":
            self._failure = str(message["reason"])[:300]
            self._ready.set()
        elif kind == "cancelled":
            self._cancel(str(message.get("reason") or "Stopped from the browser.")[:300])
        elif kind == "result":
            future = self._pending.pop(int(message["id"]), None)
            if future is not None and not future.done():
                future.set_result(message)
        elif kind == "event":
            await self._on_tab_event(message)
        elif kind == "tabAdded":
            # Tabs the page opened (openerTabId in the lease). Agent-created tabs
            # arrive only as a createTab result, so they are announced once.
            if len(self._tabs) < MAX_LEASED_TABS:
                await self._announce(self._add_tab(message["tab"], created_by_agent=True))
        elif kind == "tabUpdated":
            await self._on_tab_updated(message["tab"])
        elif kind == "tabRemoved":
            await self._on_tab_removed(int(message["tabId"]))

    async def _on_raw_frame(self, frame: str) -> None:
        header_text, _, body = frame[2:].partition("\n")
        header = json.loads(header_text)
        if frame.startswith(_RAW_RESULT):
            future = self._pending.pop(int(header["id"]), None)
            if future is not None and not future.done():
                future.set_result({"raw": _Raw(body or "{}")})
            return
        method = str(header["method"])
        if method in _PARSED_EVENTS:
            await self._on_tab_event({**header, "params": json.loads(body or "{}")})
            return
        tab = self._tabs.get(int(header["tabId"]))
        child = header.get("sessionId")
        session_id = str(child) if child else tab.page_session if tab else None
        if session_id is not None and session_id in self._sessions:
            await self._send_client_text(
                f'{{"method":{json.dumps(method)},"params":{body or "{}"},'
                f'"sessionId":{json.dumps(session_id)}}}'
            )

    def _add_tab(self, info: dict[str, Any], *, created_by_agent: bool) -> _Tab:
        tab_id = int(info["tabId"])
        existing = self._tabs.get(tab_id)
        if existing is not None:
            return existing
        if len(self._tabs) >= MAX_LEASED_TABS:
            raise ValueError("relay tab limit reached")
        tab = _Tab(
            tab_id=tab_id,
            target_id=uuid.uuid4().hex.upper(),
            url=str(info.get("url") or "about:blank"),
            title=str(info.get("title") or ""),
            created_by_agent=created_by_agent,
        )
        self._tabs[tab_id] = tab
        return tab

    async def _announce(self, tab: _Tab) -> None:
        if self._discover:
            await self._emit("Target.targetCreated", {"targetInfo": tab.target_info()})
        if self._auto_attach:
            await self._attach(tab)

    async def _on_tab_updated(self, info: dict[str, Any]) -> None:
        tab = self._tabs.get(int(info["tabId"]))
        if tab is None:
            return
        tab.url = str(info.get("url") or tab.url)
        tab.title = str(info.get("title") or tab.title)
        if self._discover:
            await self._emit("Target.targetInfoChanged", {"targetInfo": tab.target_info()})

    async def _on_tab_removed(self, tab_id: int) -> None:
        tab = self._tabs.pop(tab_id, None)
        if tab is None:
            return
        for child in tab.child_sessions:
            self._sessions.pop(child, None)
        if tab.page_session is not None:
            self._sessions.pop(tab.page_session, None)
            await self._emit(
                "Target.detachedFromTarget",
                {"sessionId": tab.page_session, "targetId": tab.target_id},
            )
        if self._discover:
            await self._emit("Target.targetDestroyed", {"targetId": tab.target_id})

    async def _on_tab_event(self, message: dict[str, Any]) -> None:
        tab = self._tabs.get(int(message["tabId"]))
        if tab is None:
            return
        method = str(message["method"])
        params = cast(dict[str, Any], message.get("params") or {})
        child = message.get("sessionId")
        session_id = str(child) if child else tab.page_session
        if session_id is None or session_id not in self._sessions:
            return
        if method == "Target.attachedToTarget" and params.get("sessionId"):
            nested = str(params["sessionId"])
            tab.child_sessions.add(nested)
            self._sessions[nested] = (tab.tab_id, nested)
        elif method == "Target.detachedFromTarget" and params.get("sessionId"):
            nested = str(params["sessionId"])
            tab.child_sessions.discard(nested)
            self._sessions.pop(nested, None)
        await self._emit(method, params, session_id)

    async def _extension_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._extension is None or self.cancelled.is_set():
            raise _CdpError("The browser extension is not connected.")
        async with self._slots:
            self._next_id += 1
            command_id = self._next_id
            future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
            self._pending[command_id] = future
            try:
                await self._extension.send(json.dumps({**payload, "id": command_id}))
                reply = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT_SECONDS)
            except TimeoutError as error:
                raise _CdpError(f"{payload.get('method') or payload['type']} timed out.") from error
            finally:
                self._pending.pop(command_id, None)
        if "error" in reply:
            raise _CdpError(str(reply["error"])[:500])
        if "raw" in reply:
            return {"raw": reply["raw"]}
        return cast(dict[str, Any], reply.get("result") or {})

    async def _extension_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        """A browser-level reply the relay itself must read (small payloads only)."""
        reply = await self._extension_call(payload)
        raw = reply.get("raw")
        return cast(dict[str, Any], json.loads(raw)) if isinstance(raw, _Raw) else reply

    # ---- Browser Use side -------------------------------------------------

    async def _serve_client(self, connection: Any) -> None:
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for raw in connection:
                if isinstance(raw, bytes):
                    continue
                task = asyncio.create_task(self._answer(json.loads(raw)))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except json.JSONDecodeError:
            logger.warning("Rejected malformed CDP client frame")
        finally:
            for task in tasks:
                task.cancel()

    async def _answer(self, request: dict[str, Any]) -> None:
        request_id = request.get("id")
        method = str(request.get("method", ""))
        params = cast(dict[str, Any], request.get("params") or {})
        session_id = request.get("sessionId")
        reply: dict[str, Any] = {"id": request_id}
        if session_id:
            reply["sessionId"] = session_id
        try:
            if session_id:
                result = await self._session_command(str(session_id), method, params)
            else:
                result = await self._browser_command(method, params)
        except _CdpError as error:
            reply["error"] = {"code": error.code, "message": str(error)}
            await self._send_client(reply)
            return
        raw = result.get("raw")
        if isinstance(raw, _Raw):
            # Splice the verbatim CDP result; the large body is never re-encoded.
            envelope = json.dumps(reply)[:-1]
            await self._send_client_text(f'{envelope},"result":{raw}}}')
        else:
            reply["result"] = result
            await self._send_client(reply)

    async def _send_client(self, message: dict[str, Any]) -> None:
        await self._send_client_text(json.dumps(message))

    async def _send_client_text(self, text: str) -> None:
        if self._client is None:
            return
        with contextlib.suppress(Exception):
            async with self._send_lock:
                await self._client.send(text)

    async def _emit(
        self, method: str, params: dict[str, Any], session_id: str | None = None
    ) -> None:
        event: dict[str, Any] = {"method": method, "params": params}
        if session_id is not None:
            event["sessionId"] = session_id
        await self._send_client(event)

    async def _session_command(
        self, session_id: str, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        route = self._sessions.get(session_id)
        if route is None:
            raise _CdpError(f"Session with given id not found: {session_id}", -32001)
        if not session_method_allowed(method):
            raise _CdpError(f"'{method}' is not available to the agent in your browser.", -32601)
        tab_id, child = route
        return await self._extension_call(
            {
                "type": "command",
                "tabId": tab_id,
                "sessionId": child,
                "method": method,
                "params": params,
            }
        )

    async def _browser_command(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = self._browser_handlers().get(method)
        if handler is None:
            raise _CdpError(f"'{method}' is not available to the agent in your browser.", -32601)
        return await handler(params)

    def _browser_handlers(
        self,
    ) -> dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
        return {
            "Browser.getVersion": self._get_version,
            "Browser.setDownloadBehavior": self._acknowledge,
            "Target.setDiscoverTargets": self._set_discover,
            "Target.setAutoAttach": self._set_auto_attach,
            "Target.getTargets": self._get_targets,
            "Target.getTargetInfo": self._get_target_info,
            "Target.attachToTarget": self._attach_to_target,
            "Target.detachFromTarget": self._detach_from_target,
            "Target.createTarget": self._create_target,
            "Target.closeTarget": self._close_target,
            "Target.activateTarget": self._activate_target,
        }

    async def _acknowledge(self, _: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def _get_version(self, _: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": "1.3",
            "product": "Chrome (BROWSKI relay)",
            "revision": "",
            "userAgent": "",
            "jsVersion": "",
        }

    async def _set_discover(self, params: dict[str, Any]) -> dict[str, Any]:
        self._discover = bool(params.get("discover"))
        if self._discover:
            for tab in list(self._tabs.values()):
                await self._emit("Target.targetCreated", {"targetInfo": tab.target_info()})
        return {}

    async def _set_auto_attach(self, params: dict[str, Any]) -> dict[str, Any]:
        self._auto_attach = bool(params.get("autoAttach"))
        if self._auto_attach:
            for tab in list(self._tabs.values()):
                if tab.page_session is None:
                    await self._attach(tab)
        return {}

    async def _get_targets(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"targetInfos": [tab.target_info() for tab in self._tabs.values()]}

    async def _get_target_info(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"targetInfo": self._tab_for_target(params.get("targetId")).target_info()}

    async def _attach_to_target(self, params: dict[str, Any]) -> dict[str, Any]:
        tab = self._tab_for_target(params.get("targetId"))
        return {"sessionId": await self._attach(tab)}

    async def _attach(self, tab: _Tab) -> str:
        if tab.page_session is None:
            tab.page_session = uuid.uuid4().hex.upper()
            self._sessions[tab.page_session] = (tab.tab_id, None)
        await self._emit(
            "Target.attachedToTarget",
            {
                "sessionId": tab.page_session,
                "targetInfo": tab.target_info(),
                "waitingForDebugger": False,
            },
        )
        return tab.page_session

    async def _detach_from_target(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId", ""))
        route = self._sessions.get(session_id)
        if route is None or route[1] is not None:
            raise _CdpError("No page session with given id.", -32001)
        tab = self._tabs[route[0]]
        tab.page_session = None
        self._sessions.pop(session_id, None)
        await self._emit(
            "Target.detachedFromTarget", {"sessionId": session_id, "targetId": tab.target_id}
        )
        return {}

    async def _create_target(self, params: dict[str, Any]) -> dict[str, Any]:
        url = str(params.get("url") or "about:blank")
        if not (url == "about:blank" or url.startswith(("http://", "https://"))):
            raise _CdpError("The agent may only open web pages.")
        if len(self._tabs) >= MAX_LEASED_TABS:
            raise _CdpError(f"The agent may use at most {MAX_LEASED_TABS} tabs.")
        result = await self._extension_result(
            {"type": "createTab", "url": url, "background": bool(params.get("background"))}
        )
        tab = self._add_tab(cast(dict[str, Any], result["tab"]), created_by_agent=True)
        await self._announce(tab)
        return {"targetId": tab.target_id}

    async def _close_target(self, params: dict[str, Any]) -> dict[str, Any]:
        tab = self._tab_for_target(params.get("targetId"))
        if not tab.created_by_agent:
            raise _CdpError("The agent cannot close a tab it did not open.")
        await self._extension_call({"type": "closeTab", "tabId": tab.tab_id})
        await self._on_tab_removed(tab.tab_id)
        return {"success": True}

    async def _activate_target(self, params: dict[str, Any]) -> dict[str, Any]:
        tab = self._tab_for_target(params.get("targetId"))
        await self._extension_call({"type": "activateTab", "tabId": tab.tab_id})
        return {}

    def _tab_for_target(self, target_id: object) -> _Tab:
        for tab in self._tabs.values():
            if tab.target_id == target_id:
                return tab
        raise _CdpError("No target with given id found.", -32602)
