"""Owned API connections are reused per run and released explicitly."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from browser_agent._types import AgentObservation, TaskState, WorkingMemory
from browser_agent.agent.action_batch import PendingActionBatch
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.agent.shadow import ShadowDecisionManager
from browser_agent.providers.privacy import ProviderBoundary
from browser_agent.reasoning import (
    OpenAILunaProvider,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


class FakeResponses:
    async def parse(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            output_parsed=ReasoningDecision(
                outcome=ReasoningOutcome.ASK_USER, questions=["Which item do you want?"]
            )
        )


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class FailingCloser:
    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = context, model, effort
        raise AssertionError("The lifecycle test does not invoke reasoning")

    async def aclose(self) -> None:
        raise RuntimeError("provider close failed")


def context() -> ReasoningContext:
    return ReasoningContext(
        purpose=ReasoningPurpose.PLAN,
        task=TaskState(task="Find the requested item."),
        memory=WorkingMemory(),
        observation=AgentObservation(url="https://fixture.test/", state_generation=1),
    )


async def test_owned_client_reused_then_closed_and_reopened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeClient] = []

    def create() -> FakeClient:
        client = FakeClient()
        created.append(client)
        return client

    provider = OpenAILunaProvider()
    monkeypatch.setattr(provider, "_create_client", create)
    boundary = ProviderBoundary(provider)
    for _ in range(2):
        await boundary.reason(context(), model="test", effort=ReasoningEffort.LOW)
    assert len(created) == 1
    await boundary.aclose()
    assert created[0].close_calls == 1
    await boundary.aclose()
    assert created[0].close_calls == 1
    await boundary.reason(context(), model="test", effort=ReasoningEffort.LOW)
    assert len(created) == 2
    await boundary.aclose()
    assert created[1].close_calls == 1


async def test_injected_client_remains_owned_by_its_caller() -> None:
    client = FakeClient()
    provider = OpenAILunaProvider(client=client)
    await provider.reason(context(), model="test", effort=ReasoningEffort.LOW)
    await provider.aclose()
    assert client.close_calls == 0


async def test_finish_run_completes_remaining_cleanup_and_propagates_provider_close_error() -> None:
    class Shadow:
        def __init__(self) -> None:
            self.close_calls = 0

        async def close(self) -> None:
            self.close_calls += 1

    class Batch:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    agent = LunaDecisionAgent(None, FailingCloser())
    shadow = Shadow()
    batch = Batch()
    agent._shadow = cast(ShadowDecisionManager, shadow)  # pyright: ignore[reportPrivateUsage]
    agent._batch = cast(PendingActionBatch, batch)  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(RuntimeError, match="provider close failed"):
        await agent.finish_run()

    assert shadow.close_calls == 1
    assert batch.clear_calls == 1
    assert agent._shadow is None  # pyright: ignore[reportPrivateUsage]
    assert agent._batch is None  # pyright: ignore[reportPrivateUsage]
