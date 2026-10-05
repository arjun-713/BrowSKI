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

    def __init__(
        self,
        candidate_id: str,
        accepted: bool | None = True,
        *,
        accepted_answers: list[bool | None] | None = None,
    ) -> None:
        self.candidate_id = candidate_id
        self.accepted = accepted
        self.accepted_answers = accepted_answers
        self.states: list[str | Mapping[str, Any]] = []

    async def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        self.states.append(state)
        accepted = self.accepted
        if self.accepted_answers is not None:
            answer_index = min(len(self.states) - 1, len(self.accepted_answers) - 1)
            accepted = self.accepted_answers[answer_index]
        return DecisionResult(
            provider=self.name,
            model="fixture",
            answers={
                name: DecisionAnswer(
                    kind=question.kind,
                    value=self.candidate_id,
                    accepted=accepted,
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


async def test_decision_calls_include_safe_run_and_action_step_correlation() -> None:
    decision_provider = FakeDecisionProvider(
        "c01",
        accepted_answers=[False, True],
    )
    reasoning_provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_actions=[
                ReasoningAction(type="click", target_ref="@continue"),
                ReasoningAction(type="press", key="ENTER"),
            ],
        )
    )
    agent = LunaDecisionAgent(decision_provider, reasoning_provider)

    decision = await agent.decide(
        snapshot(),
        task_state(run_id="run-correlation", steps_taken=6),
        WorkingMemory(),
    )

    assert decision.action is not None
    assert isinstance(decision_provider.states[-1], Mapping)
    assert decision_provider.states[-1]["run_id"] == "run-correlation"
    assert decision_provider.states[-1]["steps_taken"] == 7


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


async def test_progress_after_high_replan_returns_to_system_one() -> None:
    reasoning_provider = FakeReasoningProvider(next_click())
    decision_provider = FakeDecisionProvider("c01")
    agent = LunaDecisionAgent(decision_provider, reasoning_provider)
    task = task_state(
        recovery_history=[{"step": "luna_high_replan", "reason": "complex failure"}],
        recovery_streak=0,
        replan_count=0,
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory())

    assert decision.action is not None
    assert reasoning_provider.calls == []
    assert len(decision_provider.states) == 1


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
