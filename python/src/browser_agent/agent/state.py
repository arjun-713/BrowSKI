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
    recovery_budget: dict[str, int]
    recovery_history: list[dict[str, Any]]
    after_snapshot: dict[str, Any] | None
    last_progress: dict[str, Any] | None
    pending_confirmation: bool
    risk_assessment: dict[str, Any] | None
    status: str
    result_summary: str | None
