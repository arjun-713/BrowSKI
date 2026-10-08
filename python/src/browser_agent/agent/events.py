"""Safe structured lifecycle events for the product surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from uuid import uuid4

from browser_agent.browser_code.policy import BrowserCodeTrace


class RuntimeEventType(StrEnum):
    RUN_STARTED = "RunStarted"
    RUN_RESUMED = "RunResumed"
    OBSERVATION_COMPLETED = "ObservationCompleted"
    DECISION_MADE = "DecisionMade"
    ACTION_STARTED = "ActionStarted"
    ACTION_COMPLETED = "ActionCompleted"
    VERIFICATION_COMPLETED = "VerificationCompleted"
    RECOVERY_STARTED = "RecoveryStarted"
    BROWSER_CODE_STARTED = "BrowserCodeStarted"
    BROWSER_CODE_COMPLETED = "BrowserCodeCompleted"
    CONFIRMATION_REQUIRED = "ConfirmationRequired"
    RUN_PAUSED = "RunPaused"
    RUN_STOPPED = "RunStopped"
    RUN_COMPLETED = "RunCompleted"
    RUN_FAILED = "RunFailed"


_EVENT_LABELS = {
    RuntimeEventType.RUN_STARTED: "Task started",
    RuntimeEventType.RUN_RESUMED: "Task resumed",
    RuntimeEventType.OBSERVATION_COMPLETED: "Observed browser state",
    RuntimeEventType.DECISION_MADE: "Evaluated next browser step",
    RuntimeEventType.ACTION_STARTED: "Executing browser action",
    RuntimeEventType.ACTION_COMPLETED: "Browser action executed",
    RuntimeEventType.VERIFICATION_COMPLETED: "Verified browser result",
    RuntimeEventType.RECOVERY_STARTED: "Recovering from an unverified action",
    RuntimeEventType.BROWSER_CODE_STARTED: "Transforming semantic browser data",
    RuntimeEventType.BROWSER_CODE_COMPLETED: "Checked semantic data transform",
    RuntimeEventType.CONFIRMATION_REQUIRED: "Waiting for your confirmation",
    RuntimeEventType.RUN_PAUSED: "Task paused",
    RuntimeEventType.RUN_STOPPED: "Task stopped",
    RuntimeEventType.RUN_COMPLETED: "Task completed",
    RuntimeEventType.RUN_FAILED: "Task stopped without completion",
}


@dataclass(frozen=True, slots=True)
class BrowserCodeEventMetadata:
    """Strict, content-free trace fields for an isolated data transform."""

    purpose_category: str
    reason_category: str
    script_sha256: str
    script_bytes: int
    timeout_ms: int
    max_result_bytes: int
    result_schema: str
    duration_ms: float | None = None

    def __post_init__(self) -> None:
        if self.purpose_category != "semantic_data_transform":
            raise ValueError("unsupported browser-code purpose category")
        if self.reason_category != "explicit_capability_request":
            raise ValueError("unsupported browser-code reason category")
        if re.fullmatch(r"[0-9a-f]{64}", self.script_sha256) is None:
            raise ValueError("browser-code digest must be a lowercase SHA-256 hex string")
        if type(self.script_bytes) is not int or not 1 <= self.script_bytes <= 8_192:
            raise ValueError("browser-code source byte count is invalid")
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 1_500:
            raise ValueError("browser-code timeout is invalid")
        if type(self.max_result_bytes) is not int or not 1 <= self.max_result_bytes <= 16_384:
            raise ValueError("browser-code result byte limit is invalid")
        if self.result_schema != "BrowserCodePayload":
            raise ValueError("browser-code result schema is unsupported")
        if self.duration_ms is not None and (
            type(self.duration_ms) not in (int, float)
            or not isfinite(self.duration_ms)
            or not 0 <= self.duration_ms <= 30_000
        ):
            raise ValueError("browser-code duration is invalid")

    @classmethod
    def from_trace(
        cls,
        trace: BrowserCodeTrace,
        *,
        duration_ms: float | None = None,
    ) -> BrowserCodeEventMetadata:
        """Copy only the reviewed, source-free trace envelope."""
        return cls(
            purpose_category=trace.purpose_category,
            reason_category=trace.reason_category,
            script_sha256=trace.script_sha256,
            script_bytes=trace.script_bytes,
            timeout_ms=trace.timeout_ms,
            max_result_bytes=trace.max_result_bytes,
            result_schema=trace.result_schema,
            duration_ms=duration_ms,
        )

    def to_protocol_payload(self) -> dict[str, str | int | float]:
        payload: dict[str, str | int | float] = {
            "purposeCategory": self.purpose_category,
            "reasonCategory": self.reason_category,
            "scriptSha256": self.script_sha256,
            "scriptBytes": self.script_bytes,
            "timeoutMs": self.timeout_ms,
            "maxResultBytes": self.max_result_bytes,
            "resultSchema": self.result_schema,
        }
        if self.duration_ms is not None:
            payload["durationMs"] = self.duration_ms
        return payload


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
    browser_code: BrowserCodeEventMetadata | None = None

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
        browser_code: BrowserCodeEventMetadata | None = None,
    ) -> RuntimeEvent:
        is_browser_code_event = event_type in {
            RuntimeEventType.BROWSER_CODE_STARTED,
            RuntimeEventType.BROWSER_CODE_COMPLETED,
        }
        if browser_code is not None and not is_browser_code_event:
            raise ValueError("browser-code metadata is only valid on browser-code events")
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
            browser_code=browser_code,
        )

    def to_protocol_payload(self) -> dict[str, object]:
        """Serialize using the extension protocol's camel-case field names."""
        timeline_status = {
            "running": "running",
            "completed": "completed",
            "failed": "failed",
        }.get(self.status, "info")
        payload: dict[str, object] = {
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
        if self.browser_code is not None:
            payload["browserCode"] = self.browser_code.to_protocol_payload()
        return payload
