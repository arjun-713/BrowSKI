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
import json
from types import TracebackType
from typing import Any, Self

from browser_agent._types import ElementRef, SemanticSnapshot, SnapshotDelta, TabInfo


class BrowserSession:
    """Live Chromium session owned by the Rust browser core."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._native: Any = None

    # -- lifecycle ------------------------------------------------------
    @classmethod
    def launch(cls, headless: bool = True) -> Self:
        """Create a session; use as ``async with BrowserSession.launch(): ...``.

        Opening (spawning Chromium) happens on ``__aenter__`` so the call
        itself stays synchronous and composable in ``async with``.
        """
        return cls(headless=headless)

    async def _open(self) -> None:
        from browser_agent import _core

        self._native = await asyncio.to_thread(_core.PyBrowserSession.launch, self._headless)

    def _require_open(self) -> Any:
        if self._native is None:
            raise RuntimeError("BrowserSession is not open (use `async with` or `await launch()`)")
        return self._native

    @property
    def session_id(self) -> str | None:
        if self._native is None:
            return None
        return str(self._native.session_id())

    # -- browser API ----------------------------------------------------
    async def navigate(self, url: str) -> None:
        await asyncio.to_thread(self._require_open().navigate, url)

    async def observe(self) -> SemanticSnapshot:
        raw: str = await asyncio.to_thread(self._require_open().observe_json)
        return SemanticSnapshot.model_validate(json.loads(raw))

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

    async def close(self) -> None:
        native, self._native = self._native, None
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
