"""Hybrid System One and GPT-6 Luna agent decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from browser_agent._types import (
    SemanticElement,
    SemanticKind,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.decisions import (
    DecisionAnswer,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
)


class FakeDecisionProvider(DecisionProvider):
    name = "fake-laya"

    def __init__(self, candidate_id: str, accepted: bool | None = True) -> None:
        self.candidate_id = candidate_id
        self.accepted = accepted

    async def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        _ = state
        return DecisionResult(
            provider=self.name,
            model="fixture",
            answers={
                name: DecisionAnswer(
                    kind=question.kind,
                    value=self.candidate_id,
                    accepted=self.accepted,
                )
                for name, question in questions.items()
            },
        )


class FakeReasoningProvider:
    def __init__(self, decision: ReasoningDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[ReasoningContext, str, ReasoningEffort]] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        self.calls.append((context, model, effort))
        return self.decision


def snapshot() -> SemanticSnapshot:
    element = SemanticElement(
        ref="@continue",
        id=12,
        generation=4,
        role="button",
        accessible_name="Continue",
        semantic_kind=SemanticKind.BUTTON,
        fingerprint="continue-button",
    )
    return SemanticSnapshot(
        url="https://example.test/form",
        title="Form",
        active_tab="tab-1",
        tabs=["tab-1"],
        elements=[element],
        interactive_elements=[element],
        state_generation=4,
        page_fingerprint="form-state",
    )


def task_state(**updates: Any) -> TaskState:
    return TaskState(
        task="Continue the application",
        plan_initialized=True,
        milestones=["Continue the application"],
        current_subgoal="Continue the application",
        **updates,
    )


def next_click() -> ReasoningDecision:
    return ReasoningDecision(
        outcome=ReasoningOutcome.NEXT_ACTION,
        summary="Continue the application form.",
        action=ReasoningAction(type="click", target_ref="@continue"),
    )


def test_luna_model_uses_environment_override_and_explicit_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROWSKI_LUNA_MODEL", "configured-luna-model")
    provider = FakeReasoningProvider(next_click())

    configured = LunaDecisionAgent(FakeDecisionProvider("c03"), provider)
    explicit = LunaDecisionAgent(
        FakeDecisionProvider("c03"),
        provider,
        model="explicit-luna-model",
    )

    assert configured.model == "configured-luna-model"
    assert explicit.model == "explicit-luna-model"


async def test_system_one_abstention_escalates_to_luna_with_low_effort() -> None:
    provider = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(FakeDecisionProvider("c03"), provider)

    decision = await agent.decide(
        snapshot(),
        task_state(),
        WorkingMemory(user_goal="Continue the application"),
    )

    assert decision.action is not None
    assert decision.action.type == "click"
    assert decision.action.target is not None
    assert decision.action.target.ref == "@continue"
    assert decision.action.target.generation == 4
    assert provider.calls[0][1] == "gpt-6-luna"
    assert provider.calls[0][2] == ReasoningEffort.LOW


async def test_luna_normal_replan_uses_low_effort() -> None:
    provider = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(FakeDecisionProvider("c03"), provider)
    task = task_state(
        recovery_streak=1,
        replan_count=1,
        recovery_history=[
            {
                "step": "luna_normal_replan",
                "reason": "verification failed after a normal replan",
            }
        ],
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory())

    assert decision.action is not None
    assert provider.calls[0][2] == ReasoningEffort.LOW


async def test_luna_high_replan_uses_high_effort_only_after_gate() -> None:
    provider = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(FakeDecisionProvider("c03"), provider)
    task = task_state(
        recovery_streak=2,
        replan_count=1,
        recovery_history=[
            {
                "step": "luna_high_replan",
                "reason": "the deterministic complexity gate promoted this recovery",
            }
        ],
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory())

    assert decision.action is not None
    assert provider.calls[0][2] == ReasoningEffort.HIGH


async def test_malformed_reasoning_decision_escalates_safely() -> None:
    provider = FakeReasoningProvider(None)  # type: ignore[arg-type]
    agent = LunaDecisionAgent(FakeDecisionProvider("c03"), provider)

    decision = await agent.decide(
        snapshot(),
        task_state(),
        WorkingMemory(user_goal="Continue the application"),
    )

    assert decision.action is None
    assert decision.ask_user
    assert "unavailable" in decision.ask_user[0]
