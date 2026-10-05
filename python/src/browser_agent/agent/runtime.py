"""Agent lifecycle and LangGraph-backed browser task execution."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent.graph import build_agent_graph
from browser_agent.agent.state import AgentState
from browser_agent.decisions.base import DecisionProvider
from browser_agent.session import BrowserSession


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
        interrupt_before: Sequence[str] = (),
    ) -> None:
        self.agent = agent
        self.browser = browser
        self.config = config or AgentConfig()
        self.checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self.graph = build_agent_graph(
            self.agent,
            self.browser,
            limits=self.config,
            checkpointer=self.checkpointer,
            decision_provider=decision_provider,
            interrupt_before=interrupt_before,
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
                interrupt_before=interrupt_before,
            )

    async def run(self, task: str | TaskState, run_id: str | None = None) -> TaskState:
        """Start a task; ``run_id`` is the LangGraph checkpoint thread id."""
        thread_id = run_id or str(uuid.uuid4())
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
            "risk_assessment": None,
            "status": "running",
            "result_summary": None,
        }
        result = await self.graph.ainvoke(
            initial_state,
            self._graph_config(thread_id),
        )
        return self._task_state_from_result(result)

    async def resume(self, run_id: str) -> TaskState:
        """Resume a checkpoint, requiring explicit input for safety interrupts."""
        return await self._resume(run_id, confirmation=None)

    async def resume_with_confirmation(self, run_id: str, *, approved: bool) -> TaskState:
        """Resume a pending consequential action with an explicit user decision."""
        return await self._resume(run_id, confirmation=approved)

    async def _resume(self, run_id: str, confirmation: bool | None) -> TaskState:
        config = self._graph_config(run_id)
        checkpoint = await self.graph.aget_state(config)
        pending = checkpoint.values.get("pending_confirmation") is True
        if pending and confirmation is None:
            raise ValueError("pending high-risk actions require explicit confirmation")
        graph_input: Any = Command(resume=confirmation) if pending else None
        result = await self.graph.ainvoke(graph_input, config)
        return self._task_state_from_result(result)

    @staticmethod
    def _task_state_from_result(result: dict[str, Any]) -> TaskState:
        task_state = TaskState.model_validate(result["task_state"])
        status = result.get("status")
        if status in {"running", "awaiting_user", "completed", "failed"}:
            task_state.status = status
        if result.get("pending_confirmation") is True and result.get("__interrupt__"):
            task_state.status = "pending_confirmation"
        summary = result.get("result_summary")
        if isinstance(summary, str):
            task_state.result_summary = summary
        elif task_state.status == "pending_confirmation":
            task_state.result_summary = "High-risk browser action requires explicit confirmation."
        task_state.done = task_state.status == "completed"
        return task_state

    def _graph_config(self, thread_id: str) -> dict[str, object]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, self.config.max_steps * 5),
        }
