"""Agent lifecycle and LangGraph-backed browser task execution."""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from browser_agent._types import (
    AgentDecision,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.events import RuntimeEvent, RuntimeEventType
from browser_agent.agent.graph import build_agent_graph
from browser_agent.agent.state import AgentState
from browser_agent.decisions.base import DecisionProvider
from browser_agent.persistence.run_metadata import SQLiteRunMetadataStore
from browser_agent.session import BrowserSession

logger = logging.getLogger(__name__)
RuntimeEventSink = Callable[[RuntimeEvent], Awaitable[None]]


@dataclass
class AgentConfig:
    max_steps: int = 50
    max_llm_calls: int = 50
    max_stagnant_steps: int = 5
    max_history_events: int = 50
    max_recovery_actions: int = 4
    max_replans: int = 1
    confirm_high_risk: bool = True

    def __post_init__(self) -> None:
        if self.max_steps <= 0 or self.max_llm_calls <= 0:
            raise ValueError("step and decision budgets must be greater than zero")
        if self.max_stagnant_steps <= 0 or self.max_recovery_actions < 0:
            raise ValueError("stagnation and recovery budgets are invalid")
        if self.max_history_events < 0 or self.max_replans < 0:
            raise ValueError("history and replan budgets cannot be negative")


@dataclass(slots=True)
class _RunControl:
    pause_requested: bool = False
    stop_requested: bool = False
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)


class Agent(ABC):
    """Chooses a typed action from the current semantic state."""

    @abstractmethod
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        raise NotImplementedError


class AgentRuntime:
    """Owns the graph lifecycle while Rust owns browser action mechanics."""

    def __init__(
        self,
        agent: Agent,
        browser: BrowserSession,
        config: AgentConfig | None = None,
        *,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        decision_provider: DecisionProvider | None = None,
        run_metadata_store: SQLiteRunMetadataStore | None = None,
        interrupt_before: Sequence[str] = (),
        event_sink: RuntimeEventSink | None = None,
    ) -> None:
        self.agent = agent
        self.browser = browser
        self.config = config or AgentConfig()
        self.checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self.run_metadata_store = run_metadata_store
        self.session_id = str(uuid.uuid4())
        self._event_sink = event_sink
        self._event_sequence = 0
        self._run_controls: dict[str, _RunControl] = {}
        self._active_runs: set[str] = set()
        self.graph = build_agent_graph(
            self.agent,
            self.browser,
            limits=self.config,
            checkpointer=self.checkpointer,
            decision_provider=decision_provider,
            interrupt_before=interrupt_before,
            control_for_run=self._control_for_run,
            emit_event=self._emit_graph_event if event_sink is not None else None,
        )

    @classmethod
    @asynccontextmanager
    async def open_sqlite(
        cls,
        agent: Agent,
        browser: BrowserSession,
        database: str | Path = "browski-checkpoints.sqlite",
        config: AgentConfig | None = None,
        *,
        decision_provider: DecisionProvider | None = None,
        interrupt_before: Sequence[str] = (),
        event_sink: RuntimeEventSink | None = None,
    ) -> AsyncGenerator[AgentRuntime, None]:
        """Open a durable checkpointed runtime for the lifetime of a context.

        SQLite connections are owned by the asynchronous context and must not
        outlive it. Reopen the same database and run id to resume a task.
        """
        async with AsyncSqliteSaver.from_conn_string(str(database)) as checkpointer:
            yield cls(
                agent,
                browser,
                config,
                checkpointer=checkpointer,
                decision_provider=decision_provider,
                run_metadata_store=SQLiteRunMetadataStore(database),
                interrupt_before=interrupt_before,
                event_sink=event_sink,
            )

    async def run(self, task: str | TaskState, run_id: str | None = None) -> TaskState:
        """Start a task; ``run_id`` is the LangGraph checkpoint thread id."""
        thread_id = run_id or str(uuid.uuid4())
        if thread_id in self._active_runs:
            raise ValueError(f"run {thread_id!r} is already active")
        task_state = (
            task.model_copy(deep=True) if isinstance(task, TaskState) else TaskState(task=task)
        )
        task_state.run_id = thread_id
        initial_state: AgentState = {
            "task": task_state.user_goal or task_state.task,
            "task_state": task_state.model_dump(mode="json"),
            "memory": WorkingMemory(
                user_goal=task_state.user_goal or task_state.task,
                constraints=task_state.constraints,
                completed_milestones=task_state.completed,
                current_subgoal=task_state.current_subgoal,
                next_milestone=task_state.next_milestone,
                failed_strategies=task_state.failed_strategies,
            ).model_dump(mode="json"),
            "snapshot": None,
            "decision": None,
            "outcome": None,
            "action_history": [],
            "recovery_budget": {},
            "recovery_history": [],
            "after_snapshot": None,
            "last_progress": None,
            "pending_confirmation": False,
            "confirmation_approved": False,
            "risk_assessment": None,
            "status": "running",
            "result_summary": None,
        }
        self._run_controls[thread_id] = _RunControl()
        self._active_runs.add(thread_id)
        try:
            await self._emit_event(RuntimeEventType.RUN_STARTED, thread_id, 0, "running")
            if self.run_metadata_store is not None:
                await self.run_metadata_store.record_started(thread_id)
            result = await self.graph.ainvoke(
                initial_state,
                self._graph_config(thread_id),
            )
        except asyncio.CancelledError:
            await self._emit_event(
                RuntimeEventType.RUN_STOPPED,
                thread_id,
                task_state.steps_taken,
                "failed",
            )
            await self._record_run_state(
                TaskState(task=task_state.task, run_id=thread_id, status="failed")
            )
            raise
        except Exception:
            await self._emit_event(
                RuntimeEventType.RUN_FAILED,
                thread_id,
                task_state.steps_taken,
                "failed",
            )
            await self._record_run_state(
                TaskState(task=task_state.task, run_id=thread_id, status="failed")
            )
            raise
        finally:
            self._active_runs.discard(thread_id)
        task_state = self._task_state_from_result(result)
        await self._emit_terminal_event(task_state)
        await self._record_run_state(task_state)
        if task_state.status not in {"paused", "pending_confirmation", "awaiting_user"}:
            self._run_controls.pop(thread_id, None)
        return task_state

    def pause(self, run_id: str) -> None:
        """Pause after the current graph node and before another action starts."""
        if run_id not in self._active_runs:
            raise ValueError(f"run {run_id!r} is not active")
        self._control_for_run(run_id).pause_requested = True

    async def stop(self, run_id: str) -> TaskState:
        """Stop at a safe boundary; an in-flight action is verified first."""
        config = self._graph_config(run_id)
        if run_id not in self._run_controls:
            checkpoint = await self.graph.aget_state(config)
            if not checkpoint.values:
                raise ValueError(f"run {run_id!r} has no resumable checkpoint")
            self._run_controls[run_id] = _RunControl()
        else:
            checkpoint = await self.graph.aget_state(config)
        control = self._control_for_run(run_id)
        control.stop_requested = True
        control.stop_event.set()
        control.pause_requested = False
        if run_id in self._active_runs:
            return TaskState(
                task="",
                run_id=run_id,
                status="running",
                result_summary="Stop requested; finishing the current safe action boundary.",
            )
        if not checkpoint.next:
            current = TaskState.model_validate(checkpoint.values["task_state"])
            if current.status in {"completed", "failed", "stopped"}:
                self._run_controls.pop(run_id, None)
                return current
            current.status = "stopped"
            current.result_summary = "Stopped by the user while waiting for input."
            await self.graph.aupdate_state(
                config,
                {
                    "task_state": current.model_dump(mode="json"),
                    "status": "stopped",
                    "result_summary": current.result_summary,
                    "decision": None,
                    "pending_confirmation": False,
                },
                as_node="decide",
            )
            self._run_controls.pop(run_id, None)
            await self._record_run_state(current)
            return current
        return await self._resume(run_id, confirmation=False)

    async def resume(self, run_id: str) -> TaskState:
        """Resume a checkpoint, requiring explicit input for safety interrupts."""
        if run_id in self._active_runs:
            raise ValueError(f"run {run_id!r} is already active")
        control = self._control_for_run(run_id)
        if control.stop_requested:
            raise ValueError(f"run {run_id!r} has been stopped")
        control.pause_requested = False
        return await self._resume(run_id, confirmation=None)

    async def resume_with_confirmation(self, run_id: str, *, approved: bool) -> TaskState:
        """Resume a pending consequential action with an explicit user decision."""
        if run_id in self._active_runs:
            raise ValueError(f"run {run_id!r} is already active")
        control = self._control_for_run(run_id)
        if control.stop_requested:
            raise ValueError(f"run {run_id!r} has been stopped")
        control.pause_requested = False
        return await self._resume(run_id, confirmation=approved)

    async def pending_confirmation_details(self, run_id: str) -> dict[str, str]:
        """Return a bounded action and target summary for a pending approval."""
        checkpoint = await self.graph.aget_state(self._graph_config(run_id))
        if not checkpoint.values or checkpoint.values.get("pending_confirmation") is not True:
            raise ValueError(f"run {run_id!r} has no pending confirmation")
        decision = AgentDecision.model_validate(checkpoint.values.get("decision"))
        action = decision.action
        if action is None:
            raise ValueError("pending confirmation has no browser action")
        target_name = "the browser page"
        snapshot_value = checkpoint.values.get("snapshot")
        if action.target is not None and snapshot_value is not None:
            snapshot = SemanticSnapshot.model_validate(snapshot_value)
            target = next(
                (item for item in snapshot.elements if item.ref == action.target.ref),
                None,
            )
        else:
            target = None
        if action.target is not None and target is None:
            snapshot = await self.browser.observe()
            target = next(
                (item for item in snapshot.elements if item.ref == action.target.ref),
                None,
            )
        if target is not None:
            target_name = target.accessible_name or target.text or target_name
        risk_value = checkpoint.values.get("risk_assessment")
        risk_reason = "high-risk action"
        if isinstance(risk_value, dict):
            risk_record = cast(dict[str, object], risk_value)
            reason = risk_record.get("reason")
            if isinstance(reason, str) and reason.strip():
                risk_reason = reason.strip()[:200]
        action_label = "submit" if action.submit else action.type
        return {
            "action": action_label[:80],
            "target": target_name[:160],
            "reason": risk_reason,
        }

    async def _resume(self, run_id: str, confirmation: bool | None) -> TaskState:
        config = self._graph_config(run_id)
        checkpoint = await self.graph.aget_state(config)
        pending = checkpoint.values.get("pending_confirmation") is True
        if pending and confirmation is None:
            raise ValueError("pending high-risk actions require explicit confirmation")
        graph_input: Any = Command(resume=confirmation) if pending else None
        checkpoint_task = TaskState.model_validate(checkpoint.values["task_state"])
        checkpoint_task.status = "running"
        await self._emit_event(
            RuntimeEventType.RUN_RESUMED,
            run_id,
            checkpoint_task.steps_taken,
            "running",
        )
        await self._record_run_state(checkpoint_task)
        self._active_runs.add(run_id)
        try:
            result = await self.graph.ainvoke(graph_input, config)
        except asyncio.CancelledError:
            checkpoint_task = TaskState.model_validate(checkpoint.values["task_state"])
            checkpoint_task.status = "failed"
            await self._emit_event(
                RuntimeEventType.RUN_STOPPED,
                run_id,
                checkpoint_task.steps_taken,
                "failed",
            )
            await self._record_run_state(checkpoint_task)
            raise
        except Exception:
            checkpoint_task = TaskState.model_validate(checkpoint.values["task_state"])
            checkpoint_task.status = "failed"
            await self._emit_event(
                RuntimeEventType.RUN_FAILED,
                run_id,
                checkpoint_task.steps_taken,
                "failed",
            )
            await self._record_run_state(checkpoint_task)
            raise
        finally:
            self._active_runs.discard(run_id)
        task_state = self._task_state_from_result(result)
        await self._emit_terminal_event(task_state)
        await self._record_run_state(task_state)
        if task_state.status not in {"paused", "pending_confirmation", "awaiting_user"}:
            self._run_controls.pop(run_id, None)
        return task_state

    @staticmethod
    def _task_state_from_result(result: dict[str, Any]) -> TaskState:
        task_state = TaskState.model_validate(result["task_state"])
        status = result.get("status")
        if status in {"running", "awaiting_user", "completed", "failed", "stopped"}:
            task_state.status = status
        if result.get("pending_confirmation") is True and result.get("__interrupt__"):
            task_state.status = "pending_confirmation"
        summary = result.get("result_summary")
        if isinstance(summary, str):
            task_state.result_summary = summary
        elif task_state.status == "pending_confirmation":
            task_state.result_summary = "High-risk browser action requires explicit confirmation."
        task_state.done = task_state.status == "completed"
        interrupts = result.get("__interrupt__")
        if isinstance(interrupts, tuple):
            interrupt_items = cast(tuple[object, ...], interrupts)
        elif isinstance(interrupts, list):
            interrupt_items = tuple(cast(list[object], interrupts))
        else:
            interrupt_items = ()
        if any(_interrupt_kind(item) == "user_pause" for item in interrupt_items):
            task_state.status = "paused"
            task_state.result_summary = "Paused by the user. Resume to continue."
        return task_state

    def _control_for_run(self, run_id: str) -> _RunControl:
        control = self._run_controls.get(run_id)
        if control is None:
            control = _RunControl()
            self._run_controls[run_id] = control
        return control

    async def _emit_graph_event(
        self,
        event_type: RuntimeEventType,
        run_id: str,
        step: int,
        status: str,
    ) -> None:
        await self._emit_event(event_type, run_id, step, status)

    async def _emit_terminal_event(self, task_state: TaskState) -> None:
        terminal_events = {
            "paused": RuntimeEventType.RUN_PAUSED,
            "completed": RuntimeEventType.RUN_COMPLETED,
            "failed": RuntimeEventType.RUN_FAILED,
            "stopped": RuntimeEventType.RUN_STOPPED,
        }
        event_type = terminal_events.get(task_state.status)
        if event_type is not None and task_state.run_id is not None:
            status = "completed" if task_state.status == "completed" else "failed"
            if task_state.status in {"paused", "pending_confirmation"}:
                status = "running"
            await self._emit_event(
                event_type,
                task_state.run_id,
                task_state.steps_taken,
                status,
            )

    async def _emit_event(
        self,
        event_type: RuntimeEventType,
        run_id: str,
        step: int,
        status: str,
    ) -> None:
        sink = self._event_sink
        if sink is None:
            return
        self._event_sequence += 1
        event = RuntimeEvent.create(
            session_id=self.session_id,
            run_id=run_id,
            sequence=self._event_sequence,
            step=step,
            event_type=event_type,
            status=status,
        )
        try:
            await asyncio.wait_for(sink(event), timeout=0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "runtime trace consumer failed; disabling trace delivery",
                extra={"event_type": event_type.value},
            )
            self._event_sink = None

    async def _record_run_state(self, task_state: TaskState) -> None:
        if self.run_metadata_store is None or task_state.run_id is None:
            return
        status = task_state.status
        if status not in {
            "running",
            "paused",
            "awaiting_user",
            "pending_confirmation",
            "completed",
            "failed",
            "stopped",
        }:
            raise ValueError(f"unsupported run status {status!r}")
        await self.run_metadata_store.record_state(
            task_state.run_id,
            status=status,
            steps=task_state.steps_taken,
            reasoning_calls=task_state.llm_calls,
        )

    def _graph_config(self, thread_id: str) -> dict[str, object]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, self.config.max_steps * 5),
        }


def _interrupt_kind(item: object) -> str | None:
    value = getattr(item, "value", None)
    if not isinstance(value, dict):
        return None
    kind = cast(dict[str, object], value).get("kind")
    return kind if isinstance(kind, str) else None
