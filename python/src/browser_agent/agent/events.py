"""Safe structured lifecycle events for the product surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class RuntimeEventType(StrEnum):
    RUN_STARTED = "RunStarted"
    RUN_RESUMED = "RunResumed"
    OBSERVATION_COMPLETED = "ObservationCompleted"
    DECISION_MADE = "DecisionMade"
    ACTION_STARTED = "ActionStarted"
    ACTION_COMPLETED = "ActionCompleted"
    VERIFICATION_COMPLETED = "VerificationCompleted"
    RECOVERY_STARTED = "RecoveryStarted"
    CONFIRMATION_REQUIRED = "ConfirmationRequired"
    RUN_PAUSED = "RunPaused"
    RUN_STOPPED = "RunStopped"
    RUN_COMPLETED = "RunCompleted"
    RUN_FAILED = "RunFailed"


_EVENT_LABELS = {
    RuntimeEventType.RUN_STARTED: "Task started",
    RuntimeEventType.RUN_RESUMED: "Task resumed",
    RuntimeEventType.OBSERVATION_COMPLETED: "Observed browser state",
    RuntimeEventType.DECISION_MADE: "Selected a bounded action",
    RuntimeEventType.ACTION_STARTED: "Executing browser action",
    RuntimeEventType.ACTION_COMPLETED: "Browser action executed",
    RuntimeEventType.VERIFICATION_COMPLETED: "Verified browser result",
    RuntimeEventType.RECOVERY_STARTED: "Recovering from an unverified action",
    RuntimeEventType.CONFIRMATION_REQUIRED: "Waiting for your confirmation",
    RuntimeEventType.RUN_PAUSED: "Task paused",
    RuntimeEventType.RUN_STOPPED: "Task stopped",
    RuntimeEventType.RUN_COMPLETED: "Task completed",
    RuntimeEventType.RUN_FAILED: "Task stopped without completion",
}


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Versioned, content-minimal timeline data safe to send to the extension."""

    event_id: str
    session_id: str
    run_id: str
    sequence: int
    step: int
    created_at: str
    type: RuntimeEventType
    label: str
    status: str

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        run_id: str,
        sequence: int,
        step: int,
        event_type: RuntimeEventType,
        status: str,
    ) -> RuntimeEvent:
        return cls(
            event_id=str(uuid4()),
            session_id=session_id,
            run_id=run_id,
            sequence=sequence,
            step=max(0, step),
            created_at=datetime.now(UTC).isoformat(),
            type=event_type,
            label=_EVENT_LABELS[event_type],
            status=status,
        )

    def to_protocol_payload(self) -> dict[str, str | int]:
        """Serialize using the extension protocol's camel-case field names."""
        timeline_status = {
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }.get(self.status, "info")
        return {
            "eventId": self.event_id,
            "sessionId": self.session_id,
            "runId": self.run_id,
            "sequence": self.sequence,
            "step": self.step,
            "createdAt": self.created_at,
            "type": self.type.value,
            "label": self.label,
            "status": timeline_status,
        }
