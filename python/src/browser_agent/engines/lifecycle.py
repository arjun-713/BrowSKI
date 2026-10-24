"""Task-local cancellation and safe pause boundaries; no planner or browser ownership."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from browser_agent.engines.contracts import EngineEvent, EventSink


@dataclass(frozen=True)
class ActionApproval:
    action: str
    target: str
    reason: str = ""
    approval_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        if len(self.reason) > 300:
            raise ValueError("Approval reason exceeds 300 characters.")


ApprovalSink = Callable[[ActionApproval | None], Awaitable[None]]
ApprovalHandler = Callable[[ActionApproval], Awaitable[bool]]


class TaskControl:
    def __init__(
        self,
        engine: str,
        provider: str,
        events: EventSink,
        *,
        approvals: ApprovalSink | None = None,
    ) -> None:
        self.cancel = asyncio.Event()
        self._running = asyncio.Event()
        self._running.set()
        self._engine = engine
        self._provider = provider
        self._events = events
        self._approvals = approvals
        self._pending: tuple[str, asyncio.Future[bool]] | None = None

    @property
    def approval_handler(self) -> ApprovalHandler | None:
        return self.request_approval if self._approvals is not None else None

    def respond_to_approval(self, approval_id: str, approved: bool) -> bool:
        pending = self._pending
        if pending is None or pending[0] != approval_id or pending[1].done():
            return False
        pending[1].set_result(approved)
        return True

    async def request_approval(self, request: ActionApproval, *, wait_seconds: float = 60) -> bool:
        if self._approvals is None or self.cancel.is_set() or self._pending is not None:
            return False
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending = (request.approval_id, future)
        approved = False
        try:
            await self._approvals(request)
            async with asyncio.timeout(wait_seconds):
                approved = await future
        except TimeoutError:
            approved = False
        finally:
            self._pending = None
            if not future.done():
                future.cancel()
            await self._approvals(None)
        # Clear the consumed card before waiting on an earlier Pause. The next
        # Resume may continue this exact approved action; Stop still invalidates it.
        if approved and not self.cancel.is_set():
            await self.decision_boundary()
        return approved and not self.cancel.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def stop(self) -> None:
        self.cancel.set()
        self._running.set()
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_result(False)

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
