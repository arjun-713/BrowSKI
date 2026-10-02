"""Finite System One candidates bind only to semantic browser references."""

from __future__ import annotations

from typing import Any

import pytest

from browser_agent._types import AgentObservation, ElementRef, PrunedElement
from browser_agent.decisions import (
    ActionCandidate,
    CandidateKind,
    CandidatePolicy,
    DecisionAnswer,
    DecisionProvider,
    DecisionProviderProtocolError,
    DecisionResult,
    build_action_candidates,
    select_action_candidate,
)


class CapturingProvider(DecisionProvider):
    name = "capture"

    def __init__(self, answer: str = "c01") -> None:
        self.answer = answer
        self.state: Any = None
        self.questions: Any = None

    async def evaluate(self, state: Any, questions: Any) -> DecisionResult:
        self.state = state
        self.questions = questions
        return DecisionResult(
            provider=self.name,
            model=None,
            answers={
                key: DecisionAnswer(kind=question.kind, value=self.answer)
                for key, question in questions.items()
            },
        )


def observation() -> AgentObservation:
    return AgentObservation(
        url="https://example.test/profile",
        title="Profile",
        state_generation=7,
        elements=[
            PrunedElement(
                ref="@save",
                role="button",
                name="Save",
                value="private-form-value",
                interactable=True,
            )
        ],
    )


def test_candidates_are_bounded_and_include_goal_context() -> None:
    candidates = build_action_candidates(
        "Update profile",
        "Save the new address",
        observation(),
        {"click", "scroll"},
        CandidatePolicy(max_candidates=2),
    )

    assert len(candidates) == 2
    assert candidates[0].candidate_id == "c01"
    assert "Update profile" in candidates[0].description
    assert "Save the new address" in candidates[0].description
    assert candidates[-1].kind == CandidateKind.ESCALATE_TO_PLANNER


def test_candidate_binds_to_resolved_semantic_ref_and_rejects_mismatch() -> None:
    candidate = ActionCandidate(
        candidate_id="c01",
        kind=CandidateKind.BROWSER_ACTION,
        description="click Save",
        action_type="click",
        target_ref="@save",
        observed_generation=7,
    )

    action = candidate.to_browser_action(ElementRef(ref="@save", id=12, generation=7))
    assert action is not None
    assert action.type == "click"
    assert action.target == ElementRef(ref="@save", id=12, generation=7)
    with pytest.raises(ValueError, match="resolved from its semantic reference"):
        candidate.to_browser_action(ElementRef(ref="@cancel", id=13, generation=7))


async def test_system_one_sees_finite_candidates_without_element_values() -> None:
    obs = observation()
    candidates = build_action_candidates("Update profile", "Save address", obs, {"click", "scroll"})
    provider = CapturingProvider()

    selected = await select_action_candidate(
        provider,
        task="Update profile",
        current_subgoal="Save address",
        observation=obs,
        candidates=candidates,
    )

    assert selected == candidates[0]
    assert "private-form-value" not in str(provider.state)
    assert "selector" not in str(provider.state).lower()
    assert {item["id"] for item in provider.state["candidates"]} == {
        candidate.candidate_id for candidate in candidates
    }


async def test_system_one_unknown_candidate_is_rejected() -> None:
    obs = observation()
    candidates = build_action_candidates("task", "subgoal", obs, {"click", "scroll"})
    with pytest.raises(DecisionProviderProtocolError, match="unknown candidate"):
        await select_action_candidate(
            CapturingProvider("invented"),
            task="task",
            current_subgoal="subgoal",
            observation=obs,
            candidates=candidates,
        )
