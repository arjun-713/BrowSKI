"""Translate engine diagnostics into the public extension timeline."""

from __future__ import annotations


def timeline_payload(
    event: object,
    *,
    session_id: str,
    run_id: str,
    sequence: int,
    request_id: str | None,
) -> dict[str, object] | None:
    """Translate public engine diagnostics into the existing bounded timeline."""
    import uuid
    from datetime import UTC, datetime

    from browser_agent.engines.contracts import EngineEvent

    if not isinstance(event, EngineEvent) or event.kind == "task_finished":
        return None
    kinds = {
        "provider_failed": ("DecisionMade", "Inference failed"),
        "browser_failed": ("ActionCompleted", "Browser operation failed"),
        "approval_blocked": ("ActionCompleted", "Interaction blocked by approval policy"),
        "inference_finished": ("DecisionMade", "Inference returned"),
        "task_started": ("RunStarted", "Task started"),
        "inference_started": ("DecisionStarted", "Choosing the next browser step"),
        "decision": ("DecisionMade", "Selected a browser action"),
        "action_finished": ("ActionCompleted", "Browser action executed"),
        "tab_selected": ("VerificationCompleted", "Selected browser tab"),
        "observation": ("ObservationCompleted", "Observed browser state"),
        "verification": ("VerificationCompleted", "Checked browser effect"),
        "recovery": ("RecoveryStarted", "Reobserving before another action"),
        "task_paused": ("RunPaused", "Task paused between decisions"),
        "task_resumed": ("RunResumed", "Task resumed"),
    }
    kind, label = kinds.get(event.kind, ("ObservationCompleted", "Runtime update"))
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
    return {
        "eventId": str(uuid.uuid4()),
        "sessionId": session_id,
        "runId": run_id,
        "sequence": sequence,
        "step": event.step,
        "createdAt": datetime.now(UTC).isoformat(),
        "type": kind,
        "label": label,
        "detail": detail,
        "status": "failed"
        if event.kind in {"provider_failed", "browser_failed", "approval_blocked"}
        else "running"
        if event.kind == "inference_started"
        else "info",
        **({"requestId": request_id} if request_id else {}),
    }


def result_summary(result: object) -> str:
    from browser_agent.engines.contracts import EngineResult

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
