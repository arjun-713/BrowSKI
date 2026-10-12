"""Normalize only an identical echoed plan; reject model-authored plan changes."""

import pytest
from pydantic import ValidationError

from browser_agent._types import TaskState
from browser_agent.reasoning.contracts import ReasoningAction, ReasoningOutcome
from browser_agent.reasoning.openai_wire import LunaDecisionOutput, LunaMilestoneEvidence


def test_known_plan_echo_is_not_new_action_authority() -> None:
    task = TaskState(
        task="Scroll to bottom",
        milestones=["Show bottom"],
        milestone_evidence={"Show bottom": "visible_text:Bottom"},
    )
    wire = LunaDecisionOutput(
        outcome=ReasoningOutcome.NEXT_ACTION,
        action=ReasoningAction(type="scroll", dy=600),
        milestones=task.milestones,
        milestone_evidence=[
            LunaMilestoneEvidence(milestone="Show bottom", evidence="visible_text:Bottom")
        ],
    )
    decision = wire.to_decision(task)
    assert decision.action and decision.action.dy == 600
    assert decision.milestones == [] and decision.milestone_evidence == {}
    assert task.milestones == ["Show bottom"]


def test_changed_or_unscoped_plan_echo_still_fails_domain_contract() -> None:
    task = TaskState(
        task="Scroll", milestones=["Show bottom"], milestone_evidence={"Show bottom": "Bottom"}
    )
    wire = LunaDecisionOutput(
        outcome=ReasoningOutcome.NEXT_ACTION,
        action=ReasoningAction(type="scroll", dy=600),
        milestones=["Purchase something"],
        milestone_evidence=[LunaMilestoneEvidence(milestone="Purchase something", evidence="Paid")],
    )
    with pytest.raises(ValidationError):
        wire.to_decision(task)
    with pytest.raises(ValidationError):
        wire.to_decision()


def test_actions_suggested_with_plan_are_discarded_never_execution_authority() -> None:
    wire = LunaDecisionOutput(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Open requested sites"],
        milestone_evidence=[
            LunaMilestoneEvidence(
                milestone="Open requested sites", evidence="owned_task_destination:1"
            )
        ],
        candidate_actions=[ReasoningAction(type="new_tab", url="https://example.test/")],
    )
    decision = wire.to_decision()
    assert decision.milestones == ["Open requested sites"]
    assert decision.action is None
    assert decision.candidate_actions == []
    assert len(wire.candidate_actions) == 1
