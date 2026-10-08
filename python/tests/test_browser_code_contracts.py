"""Agent-facing browser-code contracts remain typed, bounded, and ephemeral."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
from pydantic import ValidationError

from browser_agent._types import (
    AgentObservation,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.events import BrowserCodeEventMetadata, RuntimeEvent, RuntimeEventType
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.browser_code.contracts import (
    BrowserCodePayload,
    BrowserCodeProposal,
    BrowserCodeRecord,
    BrowserCodeResult,
)
from browser_agent.browser_code.policy import BrowserCodeDisabled
from browser_agent.browser_code.tool import BrowserCodeTool
from browser_agent.reasoning.contracts import (
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
)


def _proposal(**updates: object) -> BrowserCodeProposal:
    values: dict[str, object] = {
        "script": "(snapshot) => ({summary: '1 result', records: []})",
        "purpose": "Summarize visible semantic items",
        "reason": "The requested aggregation cannot be expressed as a standard browser action.",
    }
    values.update(updates)
    return BrowserCodeProposal.model_validate(values)


def test_proposal_enforces_script_and_runtime_budgets() -> None:
    with pytest.raises(ValidationError, match="8192-byte"):
        _proposal(script="x" * 8_193)
    with pytest.raises(ValidationError):
        _proposal(timeout_ms=1_501)
    with pytest.raises(ValidationError):
        _proposal(max_result_bytes=16_385)


def test_reasoning_decision_requires_one_proposal_and_forbids_mixed_actions() -> None:
    with pytest.raises(ValidationError, match="requires one proposal"):
        ReasoningDecision(outcome=ReasoningOutcome.BROWSER_CODE)
    with pytest.raises(ValidationError, match="cannot combine"):
        ReasoningDecision.model_validate(
            {
                "outcome": ReasoningOutcome.BROWSER_CODE,
                "browser_code": _proposal(),
                "action": {"type": "wait", "ms": 1},
            }
        )

    decision = ReasoningDecision(
        outcome=ReasoningOutcome.BROWSER_CODE,
        browser_code=_proposal(),
    )
    assert (
        decision.bind_actions(
            # Browser-code requests do not bind browser actions.
            AgentObservation(url="https://example.test", state_generation=1)
        )
        == []
    )


def test_fixed_payload_rejects_unbounded_or_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        BrowserCodePayload.model_validate({"summary": "ok", "script": "leak"})
    with pytest.raises(ValidationError):
        BrowserCodePayload.model_validate({"records": [{"key": "x", "value": "a" * 501}]})
    with pytest.raises(ValidationError):
        BrowserCodePayload.model_validate({"records": [{"key": "x", "value": "a"}] * 33})
    with pytest.raises(ValidationError):
        BrowserCodePayload.model_validate({"records": [{"key": "count", "value": 1}]})


class FakeExecutor:
    def __init__(self, response: str) -> None:
        self.response = response
        self.scripts: list[str] = []

    def transform_snapshot_json(
        self,
        script: str,
        timeout_ms: int = 750,
        max_result_bytes: int = 16_384,
    ) -> str:
        self.scripts.append(script)
        return self.response


def test_tool_is_disabled_by_default_and_uses_one_fixed_result_schema() -> None:
    proposal = _proposal()
    executor = FakeExecutor('{"state_generation":7,"result_json":"{}"}')
    with pytest.raises(BrowserCodeDisabled):
        BrowserCodeTool().execute(proposal, executor)
    assert executor.scripts == []

    executor.response = json.dumps(
        {"state_generation": 7, "result_json": json.dumps({"summary": "ok", "records": []})}
    )
    result = BrowserCodeTool(enabled=True).execute(proposal, executor)
    assert result == BrowserCodeResult(
        state_generation=7,
        payload=BrowserCodePayload(summary="ok", records=[]),
    )
    assert executor.scripts == [proposal.script]


def test_cancelling_waiter_does_not_terminate_bounded_executor_worker() -> None:
    started = threading.Event()
    finished = threading.Event()
    timed_out = threading.Event()

    class TimedExecutor:
        def transform_snapshot_json(
            self,
            script: str,
            timeout_ms: int = 750,
            max_result_bytes: int = 16_384,
        ) -> str:
            del script, timeout_ms, max_result_bytes
            started.set()
            try:
                # Model the Rust engine's finite QuickJS deadline; its Rust
                # unit test verifies an infinite JS loop is interrupted.
                if not timed_out.wait(0.05):
                    timed_out.set()
                raise TimeoutError("bounded transform deadline elapsed")
            finally:
                finished.set()

    async def cancel_waiter() -> None:
        worker = asyncio.create_task(
            asyncio.to_thread(
                BrowserCodeTool(enabled=True).execute,
                _proposal(),
                TimedExecutor(),
            )
        )
        assert await asyncio.to_thread(started.wait, 1)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert await asyncio.to_thread(finished.wait, 1)
        assert timed_out.is_set()

    asyncio.run(cancel_waiter())


def test_browser_code_trace_metadata_never_contains_source_or_result() -> None:
    trace = BrowserCodeTool(enabled=True).prepare(_proposal()).trace
    metadata = BrowserCodeEventMetadata.from_trace(trace, duration_ms=12.5)
    event = RuntimeEvent.create(
        session_id="session-1",
        run_id="run-1",
        sequence=1,
        step=1,
        event_type=RuntimeEventType.BROWSER_CODE_COMPLETED,
        status="completed",
        browser_code=metadata,
    )

    payload = event.to_protocol_payload()
    encoded = json.dumps(payload)

    assert payload["browserCode"] == {
        "purposeCategory": "semantic_data_transform",
        "reasonCategory": "explicit_capability_request",
        "scriptSha256": trace.script_sha256,
        "scriptBytes": trace.script_bytes,
        "timeoutMs": trace.timeout_ms,
        "maxResultBytes": trace.max_result_bytes,
        "resultSchema": "BrowserCodePayload",
        "durationMs": 12.5,
    }
    assert _proposal().script not in encoded
    assert "result_json" not in encoded


class FakeReasoningProvider:
    def __init__(self) -> None:
        self.contexts: list[ReasoningContext] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        self.contexts.append(context)
        return ReasoningDecision(
            outcome=ReasoningOutcome.BROWSER_CODE,
            browser_code=_proposal(),
        )


def test_luna_advertises_capability_and_consumes_result_once() -> None:
    provider = FakeReasoningProvider()
    agent = LunaDecisionAgent(None, provider, browser_code_enabled=True)
    agent.accept_browser_code_result(
        BrowserCodeResult(
            state_generation=7,
            payload=BrowserCodePayload(
                summary="One matching item",
                records=[BrowserCodeRecord(key="count", value="1")],
            ),
        )
    )
    snapshot = SemanticSnapshot(
        url="https://example.test",
        state_generation=7,
        page_fingerprint="fixture",
    )
    task = TaskState(task="Summarize the visible items", plan_initialized=True)

    first = asyncio.run(agent.decide(snapshot, task, WorkingMemory()))
    second = asyncio.run(agent.decide(snapshot, task, WorkingMemory()))

    assert first.browser_code is not None
    assert second.browser_code is not None
    assert provider.contexts[0].browser_code_enabled is True
    assert provider.contexts[0].browser_code_result is not None
    assert provider.contexts[1].browser_code_result is None
    assert "browser_code" not in first.model_dump()


def test_luna_rejects_unadvertised_browser_code() -> None:
    provider = FakeReasoningProvider()
    agent = LunaDecisionAgent(None, provider)
    snapshot = SemanticSnapshot(
        url="https://example.test",
        state_generation=7,
        page_fingerprint="fixture",
    )
    task = TaskState(task="Summarize the visible items", plan_initialized=True)

    result = asyncio.run(agent.decide(snapshot, task, WorkingMemory()))

    assert result.browser_code is None
    assert result.ask_user
    assert provider.contexts[0].browser_code_enabled is False
