"""Offline contracts for evidence-backed TASK_COMPLETE proposals."""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from browser_agent._types import (
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    VerifiedLinkOpen,
    Viewport,
    WorkingMemory,
)
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.progress.completion_policy import validate_completion_proposal
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


class ScriptedReasoningProvider:
    """Return fixed decisions without contacting a model provider."""

    def __init__(self, decision: ReasoningDecision) -> None:
        self.decision = decision
        self.calls: list[ReasoningContext] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = model, effort
        self.calls.append(context)
        return self.decision


def snapshot(*elements: SemanticElement) -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://fixture.test/workflow",
        title="Workflow",
        active_tab="main",
        tabs=["main"],
        elements=list(elements),
        interactive_elements=[element for element in elements if element.interactable],
        state_generation=1,
        page_fingerprint="workflow-page",
        viewport=Viewport(width=1000, height=800),
    )


def completion_decision(
    milestones: list[str],
    evidence: Mapping[str, str] | None = None,
    extra: Mapping[str, object] | None = None,
) -> ReasoningDecision:
    values: dict[str, object] = {
        "outcome": ReasoningOutcome.TASK_COMPLETE,
        "milestones": milestones,
        "milestone_evidence": dict(evidence or {}),
    }
    values.update(extra or {})
    return ReasoningDecision.model_validate(values)


def task_with_plan(
    milestones: list[str],
    *,
    completed: list[str] | None = None,
    progress_signals: list[str] | None = None,
    task_text: str = "Finish the workflow.",
    extra: Mapping[str, object] | None = None,
) -> TaskState:
    evidence = {milestone: f"visible_text:{milestone} complete" for milestone in milestones}
    values: dict[str, object] = {
        "task": task_text,
        "user_goal": task_text,
        "run_id": "task-completion-proposal",
        "plan_initialized": True,
        "milestones": milestones,
        "required_milestones": milestones,
        "completed": completed or [],
        "milestone_evidence": evidence,
        "progress_signals": progress_signals or [],
    }
    values.update(extra or {})
    if extra is not None and "task" in extra and "user_goal" not in extra:
        values["user_goal"] = extra["task"]
    return TaskState.model_validate(values)


def test_task_complete_requires_exact_evidence_for_every_proposed_milestone() -> None:
    with pytest.raises(ValidationError, match="each milestone requires"):
        completion_decision(
            ["Open workflow", "Save workflow"],
            {"Save workflow": "visible_text:Workflow saved"},
            extra={},
        )

    with pytest.raises(ValidationError, match="each milestone requires"):
        completion_decision(
            ["Open workflow"],
            {
                "Open workflow": "visible_text:Workflow opened",
                "Unknown step": "visible_text:Unknown step complete",
            },
            extra={},
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"action": ReasoningAction(type="click", target_ref="@save")},
        {"candidate_actions": [ReasoningAction(type="click", target_ref="@save")]},
        {"candidate_id": "c01"},
        {"candidate_ids": ["c01"]},
        {"questions": ["Should I continue?"]},
    ],
)
def test_task_complete_cannot_include_actions_candidates_or_questions(
    extra: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        completion_decision(
            ["Save workflow"],
            {"Save workflow": "visible_text:Workflow saved"},
            extra=extra,
        )


@pytest.mark.asyncio
async def test_luna_completion_keeps_current_required_ids_and_prior_steps() -> None:
    first = "Open workflow"
    second = "Save workflow"
    milestones = [first, second]
    proposal = completion_decision(
        milestones,
        {
            first: "visible_text:Workflow opened",
            second: "visible_text:Workflow saved",
        },
    )
    provider = ScriptedReasoningProvider(proposal)
    agent = LunaDecisionAgent(None, provider)
    task = task_with_plan(
        milestones,
        completed=[first],
        progress_signals=["verification_success"],
        extra={
            "milestone_evidence": {
                **proposal.milestone_evidence,
                "Removed earlier step": "owned_task_destination:8",
            }
        },
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory(user_goal=task.task))

    assert decision.done
    assert decision.milestones == [first, second]
    assert decision.milestone_evidence == proposal.milestone_evidence
    assert decision.replace_plan is False
    assert task.completed == [first]
    assert len(provider.calls) == 1

    task.milestone_evidence = decision.milestone_evidence
    accepted, pending = validate_completion_proposal(
        task,
        WorkingMemory(completed_milestones=[first]),
        snapshot(
            SemanticElement(
                ref="@status",
                role="status",
                text="Workflow opened\nWorkflow saved",
                fingerprint="status",
            )
        ),
        verified_action=True,
    )

    assert accepted
    assert pending == []
    assert task.completed == [first, second]


@pytest.mark.asyncio
async def test_luna_rejects_completion_before_a_verified_browser_effect() -> None:
    milestone = "Save workflow"
    provider = ScriptedReasoningProvider(
        completion_decision(
            [milestone],
            {milestone: "visible_text:Workflow saved"},
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = task_with_plan([milestone])

    decision = await agent.decide(snapshot(), task, WorkingMemory(user_goal=task.task))

    assert not decision.done
    assert decision.action is None
    assert decision.ask_user
    assert "verified browser effect" in decision.ask_user[0]


@pytest.mark.asyncio
async def test_luna_rejects_completion_for_unknown_milestone_ids() -> None:
    current = "Save workflow"
    provider = ScriptedReasoningProvider(
        completion_decision(
            ["Unknown milestone"],
            {"Unknown milestone": "visible_text:Workflow saved"},
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = task_with_plan(
        [current],
        progress_signals=["verification_success"],
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory(user_goal=task.task))

    assert not decision.done
    assert decision.action is None
    assert decision.ask_user
    assert "did not match" in decision.ask_user[0]


@pytest.mark.asyncio
async def test_luna_rejects_different_static_visible_phrase_as_completion_proof() -> None:
    milestone = "Save workflow"
    provider = ScriptedReasoningProvider(
        completion_decision(
            [milestone],
            {milestone: "visible_text:Registration form"},
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = task_with_plan(
        [milestone],
        progress_signals=["verification_success"],
        extra={
            "milestone_evidence": {
                milestone: "visible_text:Workflow saved",
            }
        },
    )
    current_page = snapshot(
        SemanticElement(
            ref="@heading",
            role="heading",
            text="Registration form",
            fingerprint="static-heading",
        )
    )

    decision = await agent.decide(current_page, task, WorkingMemory(user_goal=task.task))

    assert not decision.done
    assert decision.ask_user
    assert len(provider.calls) == 2
    assert [call.purpose for call in provider.calls] == [
        ReasoningPurpose.CHOOSE_ACTION,
        ReasoningPurpose.REPLAN,
    ]


@pytest.mark.parametrize("blocker", ["confirmation", "required_link", "field_value"])
def test_graph_completion_gate_keeps_user_constraints(blocker: str) -> None:
    milestone = "Finish the workflow"
    status = SemanticElement(
        ref="@status",
        role="status",
        text="Finish the workflow complete",
        fingerprint="status",
    )
    elements = [status]
    task_values: dict[str, object] = {}

    if blocker == "confirmation":
        task_values["task"] = "Finish the workflow and get my confirmation before finalizing."
    elif blocker == "required_link":
        task_values.update(
            {
                "task": "Open each product link in its own tab and finish the workflow.",
                "required_link_refs": ["@product"],
                "required_link_source_tab_id": "main",
                "required_link_source_generation": 1,
                "required_link_source_fingerprint": "workflow-page",
            }
        )
        elements.append(
            SemanticElement(
                ref="@product",
                role="link",
                accessible_name="Product details",
                fingerprint="product-link",
            )
        )
    else:
        task_values["task"] = "Enable weekly digest and finish the workflow."
        elements.append(
            SemanticElement(
                ref="@updates",
                role="checkbox",
                accessible_name="Weekly digest",
                state=[],
                fingerprint="updates-checkbox",
            )
        )

    task = task_with_plan(
        [milestone],
        completed=[milestone],
        progress_signals=["verification_success"],
        extra=task_values,
    )
    graph_snapshot = snapshot(*elements)

    accepted, pending = validate_completion_proposal(
        task,
        WorkingMemory(completed_milestones=[milestone]),
        graph_snapshot,
        verified_action=True,
    )

    assert not accepted
    if blocker == "confirmation":
        assert any("confirmation" in item for item in pending)
    elif blocker == "required_link":
        assert "required_link_open:@product" in pending
    else:
        assert "checked_matches_task:@updates" in pending


@pytest.mark.parametrize(
    ("tabs", "expected_complete"),
    [
        (["main", "product-tab"], True),
        (["main"], False),
    ],
)
def test_graph_completion_requires_a_requested_link_in_a_current_tab(
    tabs: list[str], expected_complete: bool
) -> None:
    milestone = "Finish the research"
    task = task_with_plan(
        [milestone],
        completed=[milestone],
        progress_signals=["verification_success"],
        task_text="Open the product link in a new tab and finish the research.",
        extra={
            "required_link_refs": ["@product"],
            "required_link_source_tab_id": "main",
            "required_link_source_generation": 1,
            "required_link_source_fingerprint": "workflow-page",
            "verified_link_opens": [
                VerifiedLinkOpen(
                    source_tab_id="main",
                    source_ref="@product",
                    source_generation=1,
                    source_page_fingerprint="workflow-page",
                    opened_tab_id="product-tab",
                    link_label="Product details",
                )
            ],
        },
    )
    graph_snapshot = snapshot(
        SemanticElement(
            ref="@status",
            role="status",
            text=f"{milestone} complete",
            fingerprint="status",
        )
    ).model_copy(update={"tabs": tabs})

    accepted, pending = validate_completion_proposal(
        task,
        WorkingMemory(completed_milestones=[milestone]),
        graph_snapshot,
        verified_action=True,
    )

    assert accepted is expected_complete
    if expected_complete:
        assert pending == []
    else:
        assert "required_link_open:@product" in pending


def test_graph_completion_rejects_an_explicit_task_url_that_was_not_opened() -> None:
    milestone = "Open the catalog"
    task = task_with_plan(
        [milestone],
        completed=[milestone],
        progress_signals=["verification_success"],
        task_text="Open https://shop.test/catalog in a new tab and review it.",
        extra={"milestone_evidence": {milestone: "owned_task_destination:1"}},
    )

    accepted, pending = validate_completion_proposal(
        task,
        WorkingMemory(completed_milestones=[milestone]),
        snapshot(),
        verified_action=True,
    )

    assert not accepted
    assert "owned_task_destination:1" in pending
