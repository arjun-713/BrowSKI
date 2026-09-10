"""Agent lifecycle contract (Milestone 4; not yet executed)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory


@dataclass
class AgentConfig:
    max_steps: int = 50
    max_llm_calls: int = 50
    max_stagnant_steps: int = 5


class Agent(ABC):
    """Decides the next step given a snapshot, task state, and memory."""

    @abstractmethod
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        raise NotImplementedError


class AgentRuntime:
    """Owns the agent loop lifecycle; drives OBSERVE/DECIDE/ACT/VERIFY/UPDATE."""

    def __init__(self, agent: Agent, config: AgentConfig | None = None) -> None:
        self.agent = agent
        self.config = config or AgentConfig()
        self.history: list[str] = []

    async def run(self, task: str) -> TaskState:  # pragma: no cover - milestone 4
        raise NotImplementedError("AgentRuntime.run lands in Milestone 4 (first autonomous loop)")
