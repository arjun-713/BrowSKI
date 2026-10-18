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
        "task_started": ("RunStarted", "Task started"),
        "inference_started": ("DecisionStarted", "Choosing the next browser step"),
        "decision": ("DecisionMade", "Selected a browser action"),
        "action_finished": ("ActionCompleted", "Browser action executed"),
        "observation": ("ObservationCompleted", "Observed browser state"),
        "verification": ("VerificationCompleted", "Checked browser effect"),
        "recovery": ("RecoveryStarted", "Reobserving before another action"),
        "task_paused": ("RunPaused", "Task paused between decisions"),
        "task_resumed": ("RunResumed", "Task resumed"),
    }
    kind, label = kinds.get(event.kind, ("ObservationCompleted", "Runtime update"))
    detail = f"{event.engine} / {event.provider}"
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
        "status": "running" if event.kind == "inference_started" else "info",
        **({"requestId": request_id} if request_id else {}),
    }
