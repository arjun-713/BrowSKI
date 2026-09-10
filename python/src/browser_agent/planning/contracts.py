"""Planner contracts: next-action decisions; hierarchical planning later."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory


@dataclass
class Plan:
    """Placeholder plan schema; hierarchical planning lands in Milestone 4+."""

    goal: str = ""
    steps: list[str] = field(default_factory=list[str])


class Planner(ABC):
    @abstractmethod
    async def next(
        self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
    ) -> AgentDecision:
        raise NotImplementedError
