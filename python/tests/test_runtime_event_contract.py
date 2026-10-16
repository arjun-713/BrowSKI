from __future__ import annotations

import asyncio
from threading import Event, Lock
from typing import Any, cast

import pytest

from browser_agent._types import (
    AgentDecision,
    FailureKind,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent import Agent, AgentRuntime
from browser_agent.agent.events import RuntimeEvent, RuntimeEventType, SafeFailureEnvelope
from browser_agent.session import BrowserSession


class NativeBrowserFailure(RuntimeError):
    component = "browser_core"
    operation = "observe"
    native_error_type = "NAVIGATION_FAILED"
    failure_kind = "NAVIGATION"
    recoverable = True


class InvalidNativeMetadataFailure(RuntimeError):
    component = "../private-page"
    operation = "send secret"


class EventProbeBrowser:
    session_id = "rust-browser-session"

    def __init__(self, order: list[str], error: BaseException | None = None) -> None:
        self.order = order
        self.error = error

    async def observe(self) -> SemanticSnapshot:
        self.order.append("browser.observe")
        if self.error is not None:
            raise self.error
        return SemanticSnapshot(
            url="about:blank",
            page_fingerprint="empty-page",
            state_generation=0,
        )


class LockingNativeSession:
    def __init__(self) -> None:
        self.lock = Lock()
        self.observation_started = Event()
        self.release_observation = Event()
        self.session_id_called = False

    def observe_json(self) -> str:
        with self.lock:
            self.observation_started.set()
            self.release_observation.wait(timeout=2)
        return SemanticSnapshot(
            url="about:blank",
            page_fingerprint="empty-page",
            state_generation=0,
        ).model_dump_json()

    def session_id(self) -> str:
        self.session_id_called = True
        with self.lock:
            return "native-session"


class AskForClarificationAgent(Agent):
    def __init__(self, order: list[str]) -> None:
        self.order = order

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        self.order.append("agent.decide")
        return AgentDecision(ask_user=["Which item should I choose?"])


def test_run_failed_payload_carries_only_safe_native_failure_metadata() -> None:
    secret_detail = "private page content and native exception text"
    failure = SafeFailureEnvelope.from_exception(NativeBrowserFailure(secret_detail))
    event = RuntimeEvent.create(
        session_id="attachment-session-1",
        browser_session_id="rust-browser-session-1",
        request_id="request-1",
        trace_id="run-1",
        step_id="run-1:3",
        run_id="run-1",
        sequence=4,
        step=3,
        event_type=RuntimeEventType.RUN_FAILED,
        status="failed",
        failure=failure,
    )

    payload = event.to_protocol_payload()

    assert payload["browserSessionId"] == "rust-browser-session-1"
    assert payload["requestId"] == "request-1"
    assert payload["traceId"] == "run-1"
    assert payload["stepId"] == "run-1:3"
    assert payload["failure"] == {
        "component": "browser_core",
        "operation": "observe",
        "failureKind": FailureKind.NAVIGATION.value,
        "recoverable": True,
        "category": "browser",
        "debugId": failure.debug_id,
        "safeMessage": "Browser navigation failed.",
        "nativeErrorType": "NAVIGATION_FAILED",
    }
    assert secret_detail not in str(payload)


def test_exception_text_in_native_fields_is_replaced_by_safe_defaults() -> None:
    failure = SafeFailureEnvelope.from_exception(
        InvalidNativeMetadataFailure("sensitive exception text")
    )

    assert failure.component == "agent_runtime"
    assert failure.operation == "task_run"
    assert failure.failure_kind is FailureKind.UNKNOWN
    assert failure.recoverable is False
    assert failure.category == "runtime"


def test_provider_exception_uses_static_safe_message_and_category() -> None:
    failure = SafeFailureEnvelope.from_exception(
        type("RateLimitError", (RuntimeError,), {})("private provider response")
    )

    assert failure.category == "provider"
    assert failure.safe_message == "The AI provider rate limit was reached."
    assert failure.native_error_type == "RateLimitError"


def test_failure_metadata_is_only_valid_for_run_failed_events() -> None:
    failure = SafeFailureEnvelope.from_exception(RuntimeError("opaque"))

    with pytest.raises(ValueError, match="only valid on failed runs"):
        RuntimeEvent.create(
            session_id="session-1",
            run_id="run-1",
            sequence=1,
            step=1,
            event_type=RuntimeEventType.DECISION_MADE,
            status="completed",
            failure=failure,
        )


def test_started_event_types_are_part_of_the_runtime_contract() -> None:
    observation = RuntimeEvent.create(
        session_id="session-1",
        run_id="run-1",
        sequence=1,
        step=1,
        event_type=RuntimeEventType.OBSERVATION_STARTED,
        status="running",
    )
    decision = RuntimeEvent.create(
        session_id="session-1",
        run_id="run-1",
        sequence=2,
        step=1,
        event_type=RuntimeEventType.DECISION_STARTED,
        status="running",
    )

    assert observation.to_protocol_payload()["type"] == "ObservationStarted"
    assert decision.to_protocol_payload()["type"] == "DecisionStarted"


@pytest.mark.asyncio
async def test_trace_session_id_lookup_does_not_block_on_native_observation() -> None:
    browser = BrowserSession()
    native = LockingNativeSession()
    browser_state = cast(Any, browser)
    browser_state._native = native
    browser_state._session_id = "cached-browser-session"
    observation = asyncio.create_task(browser.observe())

    try:
        assert await asyncio.to_thread(native.observation_started.wait, 1)
        assert browser.session_id == "cached-browser-session"
        assert native.session_id_called is False
    finally:
        native.release_observation.set()

    await asyncio.wait_for(observation, timeout=1)


@pytest.mark.asyncio
async def test_started_events_precede_browser_observation_and_agent_decision() -> None:
    order: list[str] = []

    async def event_sink(event: RuntimeEvent) -> None:
        order.append(event.type.value)

    runtime = AgentRuntime(
        AskForClarificationAgent(order),
        EventProbeBrowser(order),  # type: ignore[arg-type]
        event_sink=event_sink,
        session_id="attachment-session",
        request_id="request-1",
    )

    result = await runtime.run("Ask a clarification question", run_id="run-1")

    assert result.status == "awaiting_user"
    assert order.index("ObservationStarted") < order.index("browser.observe")
    assert order.index("browser.observe") < order.index("ObservationCompleted")
    assert order.index("DecisionStarted") < order.index("agent.decide")
    assert order.index("agent.decide") < order.index("DecisionMade")
    assert runtime.session_id == "attachment-session"
    assert runtime.request_id == "request-1"


@pytest.mark.asyncio
async def test_runtime_failure_event_has_correlation_and_no_exception_text() -> None:
    secret_detail = "private form value from the page"
    order: list[str] = []
    events: list[RuntimeEvent] = []

    async def event_sink(event: RuntimeEvent) -> None:
        events.append(event)

    runtime = AgentRuntime(
        AskForClarificationAgent(order),
        EventProbeBrowser(order, NativeBrowserFailure(secret_detail)),  # type: ignore[arg-type]
        event_sink=event_sink,
        session_id="attachment-session",
        request_id="request-1",
    )

    with pytest.raises(NativeBrowserFailure):
        await runtime.run("Read this page", run_id="run-failed")

    failed = next(event for event in events if event.type is RuntimeEventType.RUN_FAILED)
    payload = failed.to_protocol_payload()
    assert payload["browserSessionId"] == "rust-browser-session"
    assert payload["requestId"] == "request-1"
    assert payload["traceId"] == "run-failed"
    assert payload["stepId"] == "run-failed:0"
    assert payload["failure"]["failureKind"] == FailureKind.NAVIGATION.value  # type: ignore[index]
    assert secret_detail not in str(payload)
