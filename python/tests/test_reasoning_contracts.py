from __future__ import annotations

import pytest
from pydantic import ValidationError

from browser_agent._types import AgentObservation, PrunedElement, TaskState, WorkingMemory
from browser_agent.reasoning import (
    ComplexityGate,
    ComplexityLevel,
    ComplexityReason,
    ComplexitySignals,
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


def observation(*refs: str, generation: int = 7) -> AgentObservation:
    return AgentObservation(
        url="https://example.test/form",
        state_generation=generation,
        elements=[PrunedElement(ref=ref, role="button", name=ref) for ref in refs],
    )


def test_reasoning_action_binds_only_current_semantic_ref() -> None:
    current_observation = observation("@submit")
    action = ReasoningAction(type="click", target_ref="@submit")

    bound = action.bind(current_observation)

    assert bound.type == "click"
    assert bound.target is not None
    assert bound.target.ref == "@submit"
    assert bound.target.generation == 7


def test_reasoning_action_rejects_ref_missing_from_observation() -> None:
    action = ReasoningAction(type="click", target_ref="@invented")

    with pytest.raises(ValueError, match="absent from the current observation"):
        action.bind(observation("@submit"))


def test_reasoning_action_rejects_non_interactable_ref() -> None:
    current_observation = AgentObservation(
        url="https://example.test/form",
        state_generation=7,
        elements=[PrunedElement(ref="@submit", role="button", interactable=False)],
    )

    with pytest.raises(ValueError, match="not interactable"):
        ReasoningAction(type="click", target_ref="@submit").bind(current_observation)


def test_reasoning_action_rejects_selector_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ReasoningAction.model_validate(
            {"type": "click", "target_ref": "@submit", "selector": "#submit"}
        )


def test_reasoning_action_requires_semantic_targets_and_required_values() -> None:
    with pytest.raises(ValidationError, match="semantic target_ref"):
        ReasoningAction(type="click")

    with pytest.raises(ValidationError, match="type action requires text"):
        ReasoningAction(type="type", target_ref="@search")


def test_decision_is_structured_and_candidate_set_is_bounded() -> None:
    decision = ReasoningDecision(
        outcome=ReasoningOutcome.NEXT_ACTION,
        candidate_actions=[
            ReasoningAction(type="click", target_ref="@continue"),
            ReasoningAction(type="scroll", dy=400),
        ],
    )

    bound_actions = decision.bind_actions(observation("@continue"))

    assert [action.type for action in bound_actions] == ["click", "scroll"]
    assert bound_actions[0].target is not None

    with pytest.raises(ValidationError, match="at most 8"):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_actions=[ReasoningAction(type="scroll") for _ in range(9)],
        )


def test_decision_requires_one_next_action_shape() -> None:
    with pytest.raises(ValidationError, match="exactly one action"):
        ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION)

    with pytest.raises(ValidationError, match="exactly one action"):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="scroll"),
            candidate_actions=[ReasoningAction(type="scroll")],
        )

    with pytest.raises(ValidationError, match="exactly one action"):
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_id="c01",
            action=ReasoningAction(type="activate_tab", tab="legacy-tab"),
        )


def test_milestone_plan_requires_visible_evidence_for_each_milestone() -> None:
    decision = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Open the form", "Submit the form"],
        milestone_evidence={
            "Open the form": "Registration form",
            "Submit the form": "Application complete",
        },
    )

    assert decision.milestone_evidence["Submit the form"] == "Application complete"

    with pytest.raises(ValidationError, match="deterministic visible evidence"):
        ReasoningDecision(
            outcome=ReasoningOutcome.MILESTONE_PLAN,
            milestones=["Open the form"],
        )


def test_task_complete_requires_full_plan_evidence_and_no_actions() -> None:
    completion = ReasoningDecision(
        outcome=ReasoningOutcome.TASK_COMPLETE,
        milestones=["Open form", "Save form"],
        milestone_evidence={
            "Open form": "visible_text:Registration form",
            "Save form": "visible_text:Form saved",
        },
    )
    assert completion.outcome == ReasoningOutcome.TASK_COMPLETE

    with pytest.raises(ValidationError, match="each milestone requires"):
        ReasoningDecision(
            outcome=ReasoningOutcome.TASK_COMPLETE,
            milestones=["Open form", "Save form"],
            milestone_evidence={"Save form": "visible_text:Form saved"},
        )
    with pytest.raises(ValidationError, match="only next_action decisions"):
        ReasoningDecision(
            outcome=ReasoningOutcome.TASK_COMPLETE,
            milestones=["Save form"],
            milestone_evidence={"Save form": "visible_text:Form saved"},
            candidate_id="c02",
        )
    with pytest.raises(ValidationError, match="only next_action decisions"):
        ReasoningDecision(
            outcome=ReasoningOutcome.TASK_COMPLETE,
            milestones=["Save form"],
            milestone_evidence={"Save form": "visible_text:Form saved"},
            action=ReasoningAction(type="click", target_ref="@save"),
        )


def test_reasoning_context_uses_compact_semantic_observation() -> None:
    context = ReasoningContext(
        purpose=ReasoningPurpose.PLAN,
        task=TaskState(task="Complete the form"),
        memory=WorkingMemory(user_goal="Complete the form"),
        observation=observation("@name", "@continue"),
    )

    serialized = context.model_dump(mode="json")

    assert serialized["purpose"] == "plan"
    assert [item["ref"] for item in serialized["observation"]["elements"]] == [
        "@name",
        "@continue",
    ]
    assert "selector" not in str(serialized)


def test_complexity_gate_ignores_single_failure_and_single_uncertainty() -> None:
    result = ComplexityGate().evaluate(
        ComplexitySignals(
            recovery_count=1,
            replan_count=0,
            uncertain_verification_count=1,
            repeated_state_fingerprint_count=0,
            active_subgoal_count=1,
            task_dependency_depth=1,
            semantic_ambiguity_count=1,
            plan_state_mismatch_count=1,
            tab_count=1,
        )
    )

    assert result.level == ComplexityLevel.NORMAL
    assert result.reasons == ()
    assert result.effort == "low"


def test_complexity_gate_promotes_repeated_recovery_and_ambiguity() -> None:
    result = ComplexityGate().evaluate(
        ComplexitySignals(
            recovery_count=3,
            semantic_ambiguity_count=2,
            repeated_state_fingerprint_count=2,
        )
    )

    assert result.level == ComplexityLevel.VERY_COMPLEX
    assert result.effort == "high"
    assert result.reasons == (
        ComplexityReason.REPEATED_RECOVERY,
        ComplexityReason.REPEATED_STATE,
        ComplexityReason.SEMANTIC_AMBIGUITY,
    )


def test_complexity_gate_promotes_cross_tab_synthesis_and_failed_normal_replan() -> None:
    result = ComplexityGate().evaluate(
        ComplexitySignals(
            tab_count=3,
            cross_tab_synthesis_required=True,
            normal_replan_failed=True,
        )
    )

    assert result.level == ComplexityLevel.VERY_COMPLEX
    assert result.reasons == (
        ComplexityReason.CROSS_TAB_SYNTHESIS,
        ComplexityReason.NORMAL_REPLAN_FAILED,
    )


def test_complexity_signals_reject_negative_counts() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        ComplexitySignals(recovery_count=-1)


def test_reasoning_effort_has_no_xhigh_route() -> None:
    assert {item.value for item in ReasoningEffort} == {"none", "low", "high"}
