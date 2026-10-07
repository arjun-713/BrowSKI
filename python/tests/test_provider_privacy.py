from __future__ import annotations

import pytest

from browser_agent._types import AgentObservation, PrunedElement, TaskState, WorkingMemory
from browser_agent.providers.privacy import (
    PrivacyMode,
    ProviderBoundary,
    ProviderBoundaryError,
)
from browser_agent.reasoning.contracts import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


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
            outcome=ReasoningOutcome.INTERPRETATION,
            summary=f"{model}:{effort.value}",
        )


class TokenUsingProvider(FakeReasoningProvider):
    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = model, effort
        self.contexts.append(context)
        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            summary="Use the token for the selected field.",
            action=ReasoningAction(
                type="type",
                target_ref="@email",
                text="<PRIVATE_1>",
            ),
        )


class SensitiveValueUsingProvider(FakeReasoningProvider):
    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = model, effort
        self.contexts.append(context)
        value = context.observation.elements[0].value
        assert value is not None
        return ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            summary="Fill the labeled password field.",
            action=ReasoningAction(
                type="type",
                target_ref="@secret",
                text=value,
            ),
        )


def context_with_private_values() -> ReasoningContext:
    return ReasoningContext(
        purpose=ReasoningPurpose.PLAN,
        task=TaskState(
            task="Find a role and contact me at arjun@example.test",
            user_goal="Use phone +91 98765 43210",
        ),
        memory=WorkingMemory(
            user_goal="Contact arjun@example.test",
            acquired_facts={
                "note": "Credential sk-1234567890abcdef is on the page",
                "accessToken": "sensitive-access-token-value",
            },
        ),
        observation=AgentObservation(
            url="https://example.test/form",
            title="Application",
            state_generation=4,
            elements=[
                PrunedElement(
                    ref="@password",
                    role="textbox",
                    name="Account password",
                    value="long-human-password-without-a-provider-key-prefix",
                    interactable=True,
                )
            ],
        ),
    )


@pytest.mark.asyncio
async def test_privacy_first_redacts_outbound_context_and_keeps_local_mapping() -> None:
    provider = FakeReasoningProvider()
    boundary = ProviderBoundary(provider, mode=PrivacyMode.PRIVACY_FIRST)

    result = await boundary.reason(
        context_with_private_values(),
        model="gpt-6-luna",
        effort=ReasoningEffort.LOW,
    )

    outbound = provider.contexts[0].model_dump_json()
    assert "arjun@example.test" not in outbound
    assert "+91 98765 43210" not in outbound
    assert "sk-1234567890abcdef" not in outbound
    assert "sensitive-access-token-value" not in outbound
    assert "long-human-password-without-a-provider-key-prefix" not in outbound
    assert "<PRIVATE_" in outbound
    assert "gpt-6-luna:low" == result.summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field_label",
    ["Account password", "API key", "Access token", "Verification code"],
)
async def test_privacy_first_redacts_labeled_secret_fields_and_restores_action_value(
    field_label: str,
) -> None:
    provider = SensitiveValueUsingProvider()
    boundary = ProviderBoundary(provider, mode=PrivacyMode.PRIVACY_FIRST)
    context = context_with_private_values()
    private_value = "human-entered-sensitive-value-2026"
    field = context.observation.elements[0].model_copy(
        update={"name": field_label, "value": private_value}
    )
    observation = context.observation.model_copy(update={"elements": [field]})
    context = context.model_copy(update={"observation": observation})

    result = await boundary.reason(context, model="gpt-6-luna", effort=ReasoningEffort.LOW)

    outbound = provider.contexts[0].model_dump_json()
    assert private_value not in outbound
    assert "<PRIVATE_" in outbound
    assert result.action is not None
    assert result.action.text == private_value
    assert private_value not in result.summary


@pytest.mark.asyncio
async def test_standard_mode_preserves_context_without_logging_payload() -> None:
    provider = FakeReasoningProvider()
    boundary = ProviderBoundary(provider, mode=PrivacyMode.STANDARD)
    context = context_with_private_values()

    metadata = boundary.inspect(context)
    await boundary.reason(context, model="gpt-6-luna", effort=ReasoningEffort.LOW)

    assert provider.contexts[0] is context
    assert metadata.context_characters > 0
    assert "arjun@example.test" not in metadata.model_dump_json()
    assert not hasattr(metadata, "payload")


@pytest.mark.asyncio
async def test_privacy_first_restores_private_values_only_to_local_action_fields() -> None:
    provider = TokenUsingProvider()
    boundary = ProviderBoundary(provider, mode=PrivacyMode.PRIVACY_FIRST)
    context = ReasoningContext(
        purpose=ReasoningPurpose.CHOOSE_ACTION,
        task=TaskState(task="Enter arjun@example.test in the form"),
        memory=WorkingMemory(user_goal="Enter arjun@example.test"),
        observation=AgentObservation(
            url="https://example.test/form",
            title="Contact form",
            state_generation=4,
            elements=[
                PrunedElement(
                    ref="@email",
                    role="textbox",
                    name="Email",
                    value="arjun@example.test",
                    interactable=True,
                )
            ],
        ),
    )

    result = await boundary.reason(
        context,
        model="gpt-6-luna",
        effort=ReasoningEffort.LOW,
    )

    assert "arjun@example.test" not in provider.contexts[0].model_dump_json()
    assert result.action is not None
    assert result.action.text == "arjun@example.test"
    assert "arjun@example.test" not in result.summary


@pytest.mark.asyncio
async def test_offline_mode_blocks_remote_provider_before_call() -> None:
    provider = FakeReasoningProvider()
    boundary = ProviderBoundary(provider, mode=PrivacyMode.OFFLINE)

    with pytest.raises(ProviderBoundaryError, match="offline"):
        await boundary.reason(
            context_with_private_values(),
            model="gpt-6-luna",
            effort=ReasoningEffort.LOW,
        )

    assert provider.contexts == []


def test_provider_context_size_is_bounded_before_forwarding() -> None:
    provider = FakeReasoningProvider()
    boundary = ProviderBoundary(provider, max_context_characters=100)

    with pytest.raises(ProviderBoundaryError, match="configured limit"):
        boundary.inspect(context_with_private_values())

    assert provider.contexts == []
