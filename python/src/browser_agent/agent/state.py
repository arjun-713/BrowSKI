"""Serializable state channels owned by the LangGraph agent workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class SnapshotCheckpoint(TypedDict):
    """Small browser locator/status summary; never contains page content."""

    url: str
    title: str | None
    active_tab: str | None
    page_fingerprint: str
    state_generation: int
    element_count: int


class AgentState(TypedDict):
    """Checkpoint-safe task state; live browser/provider objects stay outside it."""

    task: str
    task_state: dict[str, Any]
    memory: dict[str, Any]
    snapshot: SnapshotCheckpoint | None
    decision: dict[str, Any] | None
    outcome: dict[str, Any] | None
    action_history: list[dict[str, Any]]
    recovery_budget: dict[str, int]
    recovery_history: list[dict[str, Any]]
    after_snapshot: SnapshotCheckpoint | None
    last_progress: dict[str, Any] | None
    pending_confirmation: bool
    confirmation_approved: bool
    risk_assessment: dict[str, Any] | None
    status: str
    result_summary: str | None
