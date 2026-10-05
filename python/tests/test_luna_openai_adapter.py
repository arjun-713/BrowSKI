"""Cloud-independent contract tests for the optional GPT-6 Luna adapter."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from browser_agent._types import AgentObservation, PrunedElement, TaskState, WorkingMemory
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)
from browser_agent.reasoning.openai_adapter import (
    DEFAULT_LUNA_MODEL,
    OpenAILunaProvider,
    ReasoningProviderProtocolError,
    ReasoningProviderRequestError,
    ReasoningProviderTimeout,
    ReasoningProviderUnavailable,
    ReasoningTelemetryEvent,
)


class FakeResponses:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response or SimpleNamespace(output_parsed=None)


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def make_context() -> ReasoningContext:
    observation = AgentObservation(
        url="https://example.test/",
        title="Example",
        state_generation=7,
        elements=[
            PrunedElement(
                ref="@submit",
                role="button",
                name="Continue",
                interactable=True,
            )
        ],
    )
    return ReasoningContext(
        purpose=ReasoningPurpose.PLAN,
        task=TaskState(task="Continue through the form"),
        memory=WorkingMemory(user_goal="Continue through the form"),
        observation=observation,
    )


def make_decision() -> ReasoningDecision:
    return ReasoningDecision(
        outcome=ReasoningOutcome.NEXT_ACTION,
        summary="Continue the form.",
        action=ReasoningAction(type="click", target_ref="@submit"),
    )


async def test_luna_adapter_uses_bounded_structured_responses_request() -> None:
    responses = FakeResponses(SimpleNamespace(output_parsed=make_decision()))
    provider = OpenAILunaProvider(
        FakeClient(responses),
        max_output_tokens=640,
    )

    decision = await provider.reason(
        make_context(),
        model=DEFAULT_LUNA_MODEL,
        effort=ReasoningEffort.HIGH,
    )

    assert decision.action is not None
    assert decision.action.target_ref == "@submit"
    assert len(responses.calls) == 1
    call = responses.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert call["reasoning"] == {"effort": "high"}
    assert call["text_format"] is ReasoningDecision
    assert call["max_output_tokens"] == 640
    assert call["timeout"] == 30.0
    assert "Continue through the form" in str(call["input"])


async def test_luna_emits_correlated_token_usage_without_context_content() -> None:
    events: list[ReasoningTelemetryEvent] = []
    context = make_context().model_copy(
        update={"task": TaskState(task="Private browser goal", run_id="run-luna-1", steps_taken=6)}
    )
    response = SimpleNamespace(
        output_parsed=make_decision(),
        usage=SimpleNamespace(input_tokens=256, output_tokens=43),
    )
    provider = OpenAILunaProvider(FakeClient(FakeResponses(response)), telemetry=events.append)

    await provider.reason(context, effort=ReasoningEffort.HIGH)

    assert len(events) == 1
    event = events[0]
    assert event.provider == "openai"
    assert event.operation == "reason"
    assert event.outcome == "success"
    assert event.model == DEFAULT_LUNA_MODEL
    assert event.effort == "high"
    assert event.run_id == "run-luna-1"
    assert event.step == 7
    assert event.input_tokens == 256
    assert event.output_tokens == 43
    assert not hasattr(event, "task")


async def test_luna_adapter_applies_high_effort_then_returns_to_low() -> None:
    response = SimpleNamespace(output_parsed=make_decision())
    responses = FakeResponses(response)
    provider = OpenAILunaProvider(FakeClient(responses))

    await provider.reason(make_context(), effort=ReasoningEffort.HIGH)
    await provider.reason(make_context(), effort=ReasoningEffort.LOW)

    assert [call["reasoning"] for call in responses.calls] == [
        {"effort": "high"},
        {"effort": "low"},
    ]
    assert all(call["model"] == DEFAULT_LUNA_MODEL for call in responses.calls)


async def test_luna_adapter_rejects_semantic_refs_missing_from_sent_observation() -> None:
    bad_decision = ReasoningDecision(
        outcome=ReasoningOutcome.NEXT_ACTION,
        action=ReasoningAction(type="click", target_ref="@invented"),
    )
    responses = FakeResponses(SimpleNamespace(output_parsed=bad_decision))

    with pytest.raises(ReasoningProviderProtocolError, match="decision contract"):
        await OpenAILunaProvider(FakeClient(responses)).reason(make_context())


async def test_luna_adapter_rejects_missing_structured_output() -> None:
    provider = OpenAILunaProvider(FakeClient(FakeResponses(SimpleNamespace(output_parsed=None))))

    with pytest.raises(ReasoningProviderProtocolError, match="parsed decision"):
        await provider.reason(make_context())


async def test_luna_adapter_bounds_context_before_calling_client() -> None:
    responses = FakeResponses(SimpleNamespace(output_parsed=make_decision()))
    provider = OpenAILunaProvider(
        FakeClient(responses),
        max_context_characters=10,
    )

    with pytest.raises(ReasoningProviderProtocolError, match="character limit"):
        await provider.reason(make_context())

    assert responses.calls == []


async def test_luna_adapter_translates_request_errors_without_leaking_message() -> None:
    secret = "private-prompt-fragment"
    provider = OpenAILunaProvider(FakeClient(FakeResponses(error=RuntimeError(secret))))

    with pytest.raises(ReasoningProviderRequestError) as captured:
        await provider.reason(make_context())

    assert secret not in str(captured.value)


async def test_luna_adapter_applies_deadline() -> None:
    async def wait_forever(**kwargs: object) -> object:
        _ = kwargs
        await asyncio.sleep(1)
        return SimpleNamespace(output_parsed=make_decision())

    class SlowResponses:
        async def parse(self, **kwargs: object) -> object:
            return await wait_forever(**kwargs)

    provider = OpenAILunaProvider(
        FakeClient(SlowResponses()),  # type: ignore[arg-type]
        timeout_seconds=0.01,
    )

    with pytest.raises(ReasoningProviderTimeout):
        await provider.reason(make_context())


async def test_luna_adapter_requires_credentials_for_default_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BROWSKI_OPENAI_API_KEY", raising=False)

    with pytest.raises(ReasoningProviderUnavailable, match="Set OPENAI_API_KEY"):
        await OpenAILunaProvider().reason(make_context())


@pytest.mark.skipif(
    os.environ.get("BROWSKI_LIVE_OPENAI") != "1"
    or not (os.environ.get("OPENAI_API_KEY") or os.environ.get("BROWSKI_OPENAI_API_KEY")),
    reason="Set BROWSKI_LIVE_OPENAI=1 and an OpenAI API key to enable live API tests",
)
async def test_live_gpt6_luna_responses_structured_output() -> None:
    decision = await OpenAILunaProvider().reason(make_context())

    assert isinstance(decision, ReasoningDecision)
