"""Task-local cancellation and safe pause boundaries; no planner or browser ownership."""

from __future__ import annotations

import asyncio

from browser_agent.engines.contracts import EngineEvent, EventSink


class TaskControl:
    def __init__(self, engine: str, provider: str, events: EventSink) -> None:
        self.cancel = asyncio.Event()
        self._running = asyncio.Event()
        self._running.set()
        self._engine = engine
        self._provider = provider
        self._events = events

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self.cancel.set()
        self._running.set()

    async def decision_boundary(self) -> None:
        if not self._running.is_set() and not self.cancel.is_set():
            await EngineEvent(
                kind="task_paused",
                engine=self._engine,
                provider=self._provider,
            ).publish(self._events)
            await self._running.wait()
            if not self.cancel.is_set():
                await EngineEvent(
                    kind="task_resumed",
                    engine=self._engine,
                    provider=self._provider,
                ).publish(self._events)
