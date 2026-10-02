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

from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent.graph import build_agent_graph
from browser_agent.agent.state import AgentState
from browser_agent.session import BrowserSession


@dataclass
class AgentConfig:
    max_steps: int = 50
    max_llm_calls: int = 50
    max_stagnant_steps: int = 5
    max_history_events: int = 50


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
                interrupt_before=interrupt_before,
            )

    async def run(self, task: str, run_id: str | None = None) -> TaskState:
        """Start a task; ``run_id`` is the LangGraph checkpoint thread id."""
        thread_id = run_id or str(uuid.uuid4())
        task_state = TaskState(task=task)
        initial_state: AgentState = {
            "task": task,
            "task_state": task_state.model_dump(mode="json"),
            "memory": WorkingMemory().model_dump(mode="json"),
            "snapshot": None,
            "decision": None,
            "outcome": None,
            "action_history": [],
            "status": "running",
            "result_summary": None,
        }
        result = await self.graph.ainvoke(
            initial_state,
            self._graph_config(thread_id),
        )
        return TaskState.model_validate(result["task_state"])

    async def resume(self, run_id: str) -> TaskState:
        """Resume a task from its most recent checkpoint."""
        result = await self.graph.ainvoke(None, self._graph_config(run_id))
        return TaskState.model_validate(result["task_state"])

    def _graph_config(self, thread_id: str) -> dict[str, object]:
        return {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(25, self.config.max_steps * 5),
        }
