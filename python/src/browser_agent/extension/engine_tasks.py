"""Translate engine diagnostics into the public extension timeline."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from browser_agent.engines.contracts import EngineEvent, EngineResult

_KINDS = {
    "provider_failed": ("DecisionMade", "Inference failed"),
    "browser_failed": ("ActionCompleted", "Browser operation failed"),
    "approval_blocked": ("ActionCompleted", "Interaction blocked by approval policy"),
    "inference_finished": ("DecisionMade", "Inference returned"),
    "task_started": ("RunStarted", "Task started"),
    "inference_started": ("DecisionStarted", "Choosing the next browser step"),
    "decision": ("DecisionMade", "Selected a browser action"),
    "action_started": ("ActionStarted", "Browser action started"),
    "action_finished": ("ActionCompleted", "Browser action executed"),
    "tab_selected": ("VerificationCompleted", "Selected browser tab"),
    "observation": ("ObservationCompleted", "Observed browser state"),
    "verification": ("VerificationCompleted", "Checked browser effect"),
    "recovery": ("RecoveryStarted", "Reobserving before another action"),
    "task_paused": ("RunPaused", "Task paused between decisions"),
    "task_resumed": ("RunResumed", "Task resumed"),
}
# General shows one panel line per action (its action_started label) plus
# failures, approvals and pauses; these stay in opt-in debug capture only.
_GENERAL_DIAGNOSTICS = frozenset({"inference_started", "inference_finished", "observation"})


def timeline_payload(
    event: object,
    *,
    session_id: str,
    run_id: str,
    sequence: int,
    request_id: str | None,
) -> dict[str, object] | None:
    """Translate public engine diagnostics into the existing bounded timeline."""
    if not isinstance(event, EngineEvent) or event.kind == "task_finished":
        return None
    if event.engine == "general" and (
        event.kind in _GENERAL_DIAGNOSTICS
        or (event.kind == "action_finished" and event.verified is not False)
    ):
        return None
    kind, label = _KINDS.get(event.kind, ("ObservationCompleted", "Runtime update"))
    detail = event.detail or ("" if event.engine == "general" else _diagnostic_detail(event))
    return {
        "eventId": str(uuid.uuid4()),
        "sessionId": session_id,
        "runId": run_id,
        "sequence": sequence,
        "step": event.step,
        "createdAt": datetime.now(UTC).isoformat(),
        "type": kind,
        "label": event.label or label,
        **({"detail": detail[:500]} if detail else {}),
        **({"pageUrl": event.page_url} if event.page_url else {}),
        "status": "failed"
        if event.kind in {"provider_failed", "browser_failed", "approval_blocked"}
        else "running"
        if event.kind == "inference_started"
        else "info",
        **({"requestId": request_id} if request_id else {}),
    }


def _diagnostic_detail(event: EngineEvent) -> str:
    """Fast keeps its compact provider/action diagnostics in the timeline."""
    detail = f"{event.engine} / {event.provider}"
    if event.model:
        detail += f" / {event.model}"
    if event.operation:
        detail += f" · {event.operation}"
    if event.candidate_id:
        detail += f" · target {event.candidate_id}"
    if event.latency_ms is not None:
        detail += f" · {event.latency_ms:.0f} ms inference"
    if event.verified is not None:
        detail += " · effect observed" if event.verified else " · effect unverified"
    return detail


def result_summary(result: object) -> str:
    if not isinstance(result, EngineResult):
        raise TypeError("Expected a managed engine result")
    text = (result.answer or result.status.value)[:1200]
    if result.error:
        text += f"\n{result.error}"
    text += (
        f"\n{result.engine} / {result.provider} / {result.model} · {result.steps} decisions · "
        f"{result.action_count} actions · {result.generative_calls} generative calls · "
        f"{result.recovery_count} recoveries · {result.provider_errors} provider errors · "
        f"{result.duration_ms:.0f} ms · outcome {'verified' if result.verified else 'unverified'}"
    )
    if result.failure_phase:
        text += f" · {result.failure_phase} failure"
    return text[:2000]


def result_extras(result: EngineResult) -> dict[str, object]:
    """Add bounded structured results to the v1 panel envelope."""
    return {
        **({"answer": result.answer[:4000]} if result.answer is not None else {}),
        "verdict": {
            "verified": result.verified,
            "reason": (
                result.verdict_reason
                or result.error
                or (
                    "The outcome was verified."
                    if result.verified
                    else "The outcome was not verified."
                )
            )[:500],
        },
        "stats": {
            "steps": result.steps,
            "actions": result.action_count,
            "modelCalls": result.generative_calls,
            "durationMs": round(result.duration_ms),
        },
    }
