"""Privacy-safe values that may cross the durable LangGraph checkpoint boundary."""

from __future__ import annotations

from typing import Any, cast

from browser_agent._types import AgentDecision, BrowserAction, SemanticSnapshot
from browser_agent.agent.safety import RiskAssessment, RiskCategory
from browser_agent.agent.state import SnapshotCheckpoint
from browser_agent.progress.task_state import StagnationDetector, StagnationSample


def snapshot_checkpoint(snapshot: SemanticSnapshot) -> SnapshotCheckpoint:
    """Keep page fingerprints and counts while omitting URL and title content."""
    return {
        "url": "",
        "title": None,
        "active_tab": snapshot.active_tab,
        "page_fingerprint": snapshot.page_fingerprint,
        "state_generation": snapshot.state_generation,
        "element_count": len(snapshot.elements),
    }


def snapshot_from_checkpoint(summary: SnapshotCheckpoint) -> SemanticSnapshot:
    """Build a metadata-only baseline after a process restart."""
    active_tab = summary["active_tab"]
    return SemanticSnapshot(
        url=summary["url"],
        title=summary["title"],
        tabs=[active_tab] if active_tab else [],
        active_tab=active_tab,
        page_fingerprint=summary["page_fingerprint"],
        state_generation=summary["state_generation"],
    )


def decision_checkpoint(decision: AgentDecision) -> dict[str, Any]:
    """Persist only fields needed for routing or explicit action approval."""
    checkpoint: dict[str, Any] = {"done": decision.done}
    if decision.action is not None:
        checkpoint["action"] = browser_action_checkpoint(decision.action)
    if decision.reasoning_effort is not None:
        checkpoint["reasoning_effort"] = decision.reasoning_effort
    return checkpoint


def browser_action_checkpoint(action: BrowserAction) -> dict[str, Any]:
    """Persist only fields needed to describe or safely rebind an action."""
    checkpoint: dict[str, Any] = {"type": action.type}
    if action.target is not None:
        checkpoint["target"] = action.target.model_dump(mode="json")
    if action.clear is not True:
        checkpoint["clear"] = action.clear
    if action.submit:
        checkpoint["submit"] = True
    if action.by != "value":
        checkpoint["by"] = action.by
    if action.checked is not None:
        checkpoint["checked"] = action.checked
    if action.key in {"ENTER", "Enter", "TAB", "Tab", "ESC", "Escape"}:
        checkpoint["key"] = action.key
    if action.dx:
        checkpoint["dx"] = action.dx
    if action.dy:
        checkpoint["dy"] = action.dy
    if action.tab is not None:
        checkpoint["tab"] = action.tab
    if action.accept is not None:
        checkpoint["accept"] = action.accept
    if action.ms is not None:
        checkpoint["ms"] = action.ms
    return checkpoint


def decision_from_checkpoint(data: dict[str, Any]) -> AgentDecision:
    """Rebuild a durable decision only from its explicitly safe fields."""
    checkpoint = dict(data)
    action_data = checkpoint.get("action")
    if isinstance(action_data, dict):
        checkpoint["action"] = BrowserAction.model_validate(action_data)
    return AgentDecision.model_validate(checkpoint)


def risk_checkpoint(risk: RiskAssessment) -> dict[str, str]:
    """Persist the policy category without page-derived label text."""
    return {
        "category": risk.category.value,
        "reason": "policy requires confirmation" if risk.category == RiskCategory.HIGH else "",
    }


def outcome_checkpoint(outcome: dict[str, Any]) -> dict[str, Any]:
    """Keep deterministic outcome status while dropping values and evidence."""
    execution = outcome.get("execution")
    if isinstance(execution, dict) and "Ok" in execution:
        safe_execution: dict[str, Any] = {"Ok": True}
    else:
        safe_execution = {"Err": {"kind": "ACTION_FAILED"}}

    verification = outcome.get("verification")
    if isinstance(verification, dict):
        verification_data = cast(dict[str, Any], verification)
        status = str(verification_data.get("status", "UNKNOWN"))
    else:
        status = "UNKNOWN"
    checkpoint: dict[str, Any] = {
        "execution": safe_execution,
        "verification": {"status": status},
    }
    for name in ("before_generation", "after_generation", "elapsed_ms"):
        value = nonnegative_int(outcome.get(name))
        if value is not None:
            checkpoint[name] = value
    checkpoint["timings"] = bounded_action_timings(outcome.get("timings"))
    return checkpoint


def same_checkpoint_page(
    checkpoint: SnapshotCheckpoint | None,
    snapshot: SemanticSnapshot,
) -> bool:
    return checkpoint is not None and checkpoint["page_fingerprint"] == snapshot.page_fingerprint


def nonnegative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def bounded_action_timings(value: Any) -> dict[str, int]:
    fields = (
        "pre_observation_ms",
        "target_resolution_ms",
        "action_execution_ms",
        "mechanical_recovery_ms",
        "settle_ms",
        "post_observation_ms",
        "delta_ms",
        "verification_ms",
    )
    if not isinstance(value, dict):
        return {}
    timing_values = cast(dict[str, Any], value)
    return {
        name: bounded
        for name in fields
        if (bounded := nonnegative_int(timing_values.get(name))) is not None
    }


def action_audit_summary(action: Any) -> dict[str, str]:
    """Keep checkpoint and confirmation summaries free of submitted values."""
    if not isinstance(action, dict):
        return {"type": "unknown"}
    action_data = cast(dict[str, Any], action)
    summary = {"type": str(action_data.get("type", "unknown"))}
    target = action_data.get("target")
    if isinstance(target, dict):
        target_data = cast(dict[str, Any], target)
        target_ref = target_data.get("ref")
        if isinstance(target_ref, str):
            summary["target_ref"] = target_ref
    return summary


def action_audit_signature(action: Any) -> str:
    summary = action_audit_summary(action)
    target = summary.get("target_ref")
    return f"{summary['type']}:{target}" if target else summary["type"]


def stagnation_detector(history: list[dict[str, Any]]) -> StagnationDetector:
    detector = StagnationDetector()
    for event in history:
        detector.observe(
            StagnationSample(
                state_fingerprint=str(event.get("after_fingerprint", "")),
                action_signature=str(event.get("action_signature", "")),
                verification_status=str(event.get("verification_status", "UNKNOWN")),
                progressed=bool(event.get("progressed", False)),
                recovery_kind=event.get("recovery_kind"),
            )
        )
    return detector
