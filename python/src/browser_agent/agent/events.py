"""Safe structured lifecycle events for the product surface."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from uuid import uuid4

from browser_agent._types import FailureKind
from browser_agent.browser_code.policy import BrowserCodeTrace
from browser_agent.telemetry.debug_errors import exception_debug_metadata


class RuntimeEventType(StrEnum):
    RUN_STARTED = "RunStarted"
    RUN_RESUMED = "RunResumed"
    OBSERVATION_STARTED = "ObservationStarted"
    OBSERVATION_COMPLETED = "ObservationCompleted"
    DECISION_STARTED = "DecisionStarted"
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
    RuntimeEventType.OBSERVATION_STARTED: "Observing browser state",
    RuntimeEventType.OBSERVATION_COMPLETED: "Observed browser state",
    RuntimeEventType.DECISION_STARTED: "Choosing the next browser step",
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
class SafeFailureEnvelope:
    """Bounded failure metadata that contains no exception message or page data."""

    component: str
    operation: str
    failure_kind: FailureKind
    recoverable: bool
    category: str
    debug_id: str
    safe_message: str
    native_error_type: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("component", self.component), ("operation", self.operation)):
            if re.fullmatch(r"[A-Za-z0-9_]{1,64}", value) is None:
                raise ValueError(f"failure {name} must be a bounded safe token")
        if type(self.recoverable) is not bool:
            raise ValueError("failure recoverability must be a boolean")
        if self.category not in {"browser", "provider", "persistence", "transport", "runtime"}:
            raise ValueError("failure category is unsupported")
        if re.fullmatch(r"[0-9a-f]{32}", self.debug_id) is None:
            raise ValueError("failure debug identifier must be a UUID hex string")
        if not self.safe_message or len(self.safe_message) > 200:
            raise ValueError("failure safe message must be bounded")
        if (
            self.native_error_type is not None
            and re.fullmatch(r"[A-Za-z0-9_]{1,64}", self.native_error_type) is None
        ):
            raise ValueError("native error type must be a bounded safe token")

    @classmethod
    def from_exception(cls, error: BaseException) -> SafeFailureEnvelope:
        """Translate reviewed exception metadata without copying its message."""
        native = exception_debug_metadata(error)["native"]
        component = _safe_failure_token(native.get("component"), "agent_runtime")
        operation = _safe_failure_token(native.get("operation"), "task_run")
        raw_kind = native.get("failure_kind")
        try:
            failure_kind = (
                FailureKind(raw_kind) if isinstance(raw_kind, str) else FailureKind.UNKNOWN
            )
        except ValueError:
            failure_kind = FailureKind.UNKNOWN
        recoverable = native.get("recoverable", False)
        if type(recoverable) is not bool:
            recoverable = False
        native_error_type = native.get("native_error_type")
        if not isinstance(native_error_type, str):
            candidate = type(error).__name__
            native_error_type = candidate if candidate in _PROVIDER_ERROR_TYPES else None
        else:
            native_error_type = _safe_failure_token(native_error_type, "") or None
        category = _failure_category(component, native_error_type)
        return cls(
            component=component,
            operation=operation,
            failure_kind=failure_kind,
            recoverable=recoverable,
            category=category,
            debug_id=uuid4().hex,
            safe_message=_safe_failure_message(
                component, operation, failure_kind, native_error_type
            ),
            native_error_type=native_error_type,
        )

    def to_protocol_payload(self) -> dict[str, str | bool]:
        payload: dict[str, str | bool] = {
            "component": self.component,
            "operation": self.operation,
            "failureKind": self.failure_kind.value,
            "recoverable": self.recoverable,
            "category": self.category,
            "debugId": self.debug_id,
            "safeMessage": self.safe_message,
        }
        if self.native_error_type is not None:
            payload["nativeErrorType"] = self.native_error_type
        return payload


def _safe_failure_token(value: object, fallback: str) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", value) is not None:
        return value
    return fallback


def _failure_category(component: str, native_error_type: str | None) -> str:
    normalized = component.lower()
    if any(token in normalized for token in ("provider", "luna", "model")) or (
        native_error_type in _PROVIDER_ERROR_TYPES
    ):
        return "provider"
    if any(token in normalized for token in ("checkpoint", "persistence", "sqlite")):
        return "persistence"
    if any(token in normalized for token in ("transport", "extension", "native")):
        return "transport"
    if any(token in normalized for token in ("browser", "cdp", "rust")):
        return "browser"
    return "runtime"


_PROVIDER_ERROR_TYPES = {
    "APIConnectionError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "RateLimitError",
    "InternalServerError",
}


def _safe_failure_message(
    component: str,
    operation: str,
    failure_kind: FailureKind,
    native_error_type: str | None,
) -> str:
    browser_messages = {
        "FRAME_DETACHED": "The browser frame detached during observation.",
        "TARGET_CLOSED": "The attached browser tab is no longer available.",
        "COMMAND_TIMEOUT": "A browser protocol command timed out.",
        "PROTOCOL_ERROR": "The browser rejected an observation protocol command.",
        "NAVIGATION_FAILED": "Browser navigation failed.",
        "NO_ACTIVE_TAB": "The attached browser has no active tab.",
        "CONNECTION_LOST": "The browser connection ended during observation.",
        "SESSION_CLOSED": "The browser session is closed.",
        "INVALID_RESPONSE": "The browser returned an invalid protocol response.",
        "EXTENSION_COMMAND_REJECTED": "The extension refused an unsupported browser command.",
        "EXTENSION_SESSION_MISMATCH": "The extension refused a command for another attachment.",
        "EXTENSION_COMMAND_TIMEOUT": "The extension debugger command timed out or disconnected.",
        "BRIDGE_JSON_DEPTH_LIMIT": "The browser bridge response exceeded the JSON nesting limit.",
        "BRIDGE_MESSAGE_TOO_LARGE": "The browser bridge response exceeded the message size limit.",
        "EXTENSION_BRIDGE_FAILURE": (
            "The attached browser transport could not complete observation."
        ),
    }
    provider_messages = {
        "APIConnectionError": "The AI provider could not be reached.",
        "APITimeoutError": "The AI provider took too long to respond.",
        "AuthenticationError": "The AI provider rejected the configured credentials.",
        "BadRequestError": "The AI provider rejected the request format.",
        "RateLimitError": "The AI provider rate limit was reached.",
        "InternalServerError": "The AI provider returned a temporary service error.",
    }
    if native_error_type in provider_messages:
        return provider_messages[native_error_type]
    if native_error_type in browser_messages:
        return browser_messages[native_error_type]
    if component == "browser_core" and operation == "observe":
        return f"Browser observation failed ({failure_kind.value})."
    if component == "browser_core" and operation == "execute":
        return f"Browser action failed ({failure_kind.value})."
    return f"{component} could not complete {operation} ({failure_kind.value})."


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
    browser_session_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    step_id: str | None = None
    browser_code: BrowserCodeEventMetadata | None = None
    failure: SafeFailureEnvelope | None = None

    def __post_init__(self) -> None:
        for field_name, value, limit in (
            ("browser session ID", self.browser_session_id, 128),
            ("request ID", self.request_id, 128),
            ("trace ID", self.trace_id, 128),
            ("step ID", self.step_id, 160),
        ):
            if value is not None and (not value or len(value) > limit):
                raise ValueError(f"event {field_name} is invalid")

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
        browser_session_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        step_id: str | None = None,
        browser_code: BrowserCodeEventMetadata | None = None,
        failure: SafeFailureEnvelope | None = None,
    ) -> RuntimeEvent:
        is_browser_code_event = event_type in {
            RuntimeEventType.BROWSER_CODE_STARTED,
            RuntimeEventType.BROWSER_CODE_COMPLETED,
        }
        if browser_code is not None and not is_browser_code_event:
            raise ValueError("browser-code metadata is only valid on browser-code events")
        if failure is not None and event_type is not RuntimeEventType.RUN_FAILED:
            raise ValueError("failure metadata is only valid on failed runs")
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
            browser_session_id=browser_session_id,
            request_id=request_id,
            trace_id=trace_id,
            step_id=step_id,
            browser_code=browser_code,
            failure=failure,
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
        if self.browser_session_id is not None:
            payload["browserSessionId"] = self.browser_session_id
        if self.request_id is not None:
            payload["requestId"] = self.request_id
        if self.trace_id is not None:
            payload["traceId"] = self.trace_id
        if self.step_id is not None:
            payload["stepId"] = self.step_id
        if self.browser_code is not None:
            payload["browserCode"] = self.browser_code.to_protocol_payload()
        if self.failure is not None:
            payload["failure"] = self.failure.to_protocol_payload()
        return payload
