"""Async browser session: Python facade over the Rust core (PyO3).

The native module exposes a *synchronous* ``PyBrowserSession``; this module
presents the documented async API by running blocking calls in
``asyncio.to_thread`` so event-loop threads are never stalled:

    from browser_agent import BrowserSession

    async with BrowserSession.launch() as browser:
        await browser.navigate("https://example.com")
        snapshot = await browser.observe()
        print(snapshot.title)
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
from types import TracebackType
from typing import Any, Self

from browser_agent._types import BrowserAction, ElementRef, SemanticSnapshot, SnapshotDelta, TabInfo
from browser_agent.browser_code import BrowserCodeProposal, BrowserCodeResult, BrowserCodeTool

MAX_VIEWPORT_SCREENSHOT_BYTES = 4 * 1024 * 1024


class BrowserSession:
    """Live Chromium session owned by the Rust browser core."""

    def __init__(self, headless: bool = True, *, browser_code_enabled: bool = False) -> None:
        self._headless = headless
        self._browser_code_enabled = browser_code_enabled
        self._native: Any = None
        self._session_id: str | None = None

    # -- lifecycle ------------------------------------------------------
    @classmethod
    def launch(cls, headless: bool = True, *, browser_code_enabled: bool = False) -> Self:
        """Create a session; use as ``async with BrowserSession.launch(): ...``.

        Opening (spawning Chromium) happens on ``__aenter__`` so the call
        itself stays synchronous and composable in ``async with``.
        """
        return cls(headless=headless, browser_code_enabled=browser_code_enabled)

    async def _open(self) -> None:
        from browser_agent import _core

        native = await asyncio.to_thread(
            _core.PyBrowserSession.launch, self._headless, self._browser_code_enabled
        )
        self._native = native
        self._session_id = await asyncio.to_thread(native.session_id)

    @classmethod
    async def attach_extension(
        cls,
        *,
        socket_path: str,
        token: str,
        attachment_id: str,
        session_id: str,
        target_id: str,
        title: str,
        url: str,
        browser_code_enabled: bool = False,
    ) -> Self:
        """Use the shared Rust browser core through an attached extension tab."""
        from browser_agent import _core

        session = cls(browser_code_enabled=browser_code_enabled)
        native = await asyncio.to_thread(
            _core.PyBrowserSession.attach_extension,
            socket_path,
            token,
            json.dumps(
                {
                    "attachment_id": attachment_id,
                    "session_id": session_id,
                    "target_id": target_id,
                    "title": title,
                    "url": url,
                }
            ),
            browser_code_enabled,
        )
        session._native = native
        session._session_id = await asyncio.to_thread(native.session_id)
        return session

    def _require_open(self) -> Any:
        if self._native is None:
            raise RuntimeError("BrowserSession is not open (use `async with` or `await launch()`)")
        return self._native

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # -- browser API ----------------------------------------------------
    async def navigate(self, url: str) -> None:
        await asyncio.to_thread(self._require_open().navigate, url)

    async def observe(self) -> SemanticSnapshot:
        raw: str = await asyncio.to_thread(self._require_open().observe_json)
        return SemanticSnapshot.model_validate(json.loads(raw))

    async def probe_connection(self) -> None:
        """Verify browser protocol reachability without returning page data."""
        await asyncio.to_thread(self._require_open().probe_connection)

    async def capture_viewport_screenshot(self, tab_id: str) -> bytes:
        """Capture a bounded visible-viewport PNG for on-demand vision."""
        encoded: str = await asyncio.to_thread(
            self._require_open().capture_viewport_screenshot,
            tab_id,
        )
        try:
            screenshot = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as error:
            raise RuntimeError("Rust browser core returned invalid screenshot data") from error
        if len(screenshot) > MAX_VIEWPORT_SCREENSHOT_BYTES:
            raise RuntimeError("viewport screenshot exceeds the 4 MiB image limit")
        if not screenshot.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Rust browser core returned a non-PNG viewport screenshot")
        return screenshot

    async def tabs(self) -> list[TabInfo]:
        raw: str = await asyncio.to_thread(self._require_open().tabs_json)
        return [TabInfo.model_validate(t) for t in json.loads(raw)]

    async def active_tab_id(self) -> str | None:
        return await asyncio.to_thread(self._require_open().active_tab_id)

    async def render_observation(self, tab_id: str, memory_refs: set[str] | None = None) -> str:
        """Model-facing `@ref` text for a tab (pruned, deterministic)."""
        native = self._require_open()
        return await asyncio.to_thread(native.render_observation, tab_id, sorted(memory_refs or ()))

    async def observe_delta(self, tab_id: str) -> SnapshotDelta:
        raw: str = await asyncio.to_thread(self._require_open().observe_delta_json, tab_id)
        return SnapshotDelta.model_validate(json.loads(raw))

    async def resolve(self, tab_id: str, alias: str) -> ElementRef | None:
        raw: str | None = await asyncio.to_thread(self._require_open().resolve_json, tab_id, alias)
        if raw is None:
            return None
        return ElementRef.model_validate(json.loads(raw))

    async def act(self, action: BrowserAction, tab_id: str | None = None) -> dict[str, Any]:
        """Run a typed action through the Rust executor and verifier."""
        native = self._require_open()
        selected_tab = tab_id or await self.active_tab_id()
        if selected_tab is None:
            raise RuntimeError("browser session has no active tab")
        payload = action.model_dump(mode="json", exclude_none=True)
        raw: str = await asyncio.to_thread(
            native.act_json,
            selected_tab,
            json.dumps(payload),
        )
        return json.loads(raw)

    async def execute_browser_code(self, proposal: BrowserCodeProposal) -> BrowserCodeResult:
        """Run an explicitly enabled, isolated transform over Rust-owned data."""
        tool = BrowserCodeTool(enabled=self._browser_code_enabled)
        return await asyncio.to_thread(tool.execute, proposal, self._require_open())

    async def close(self) -> None:
        native, self._native = self._native, None
        self._session_id = None
        if native is not None:
            await asyncio.to_thread(native.close)

    # -- context manager -------------------------------------------------
    async def __aenter__(self) -> Self:
        if self._native is None:
            await self._open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
