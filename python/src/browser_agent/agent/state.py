"""Serializable state channels owned by the LangGraph agent workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict):
    """Checkpoint-safe task state; live browser/provider objects stay outside it."""

    task: str
    task_state: dict[str, Any]
    memory: dict[str, Any]
    snapshot: dict[str, Any] | None
    decision: dict[str, Any] | None
    outcome: dict[str, Any] | None
    action_history: list[dict[str, Any]]
    status: str
    result_summary: str | None
