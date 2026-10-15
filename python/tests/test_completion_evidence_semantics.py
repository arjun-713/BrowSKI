"""Visible names and negated status messages cannot prove an action's effect."""

from test_microtask_call_budget import ScriptedReasoningProvider

from browser_agent._types import SemanticElement, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.progress.evidence import advance_observed_milestones, visible_phrase_present
from browser_agent.reasoning import ReasoningDecision, ReasoningOutcome


def page(*elements: SemanticElement) -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://fixture.test/",
        page_fingerprint="completion-test",
        state_generation=1,
        elements=list(elements),
    )


def text(value: str) -> SemanticElement:
    return SemanticElement(ref="@status", role="status", text=value, fingerprint="status")


def test_button_label_does_not_prove_next_stage_is_visible() -> None:
    button = SemanticElement(
        ref="@continue",
        role="button",
        accessible_name="Continue to workshop choices",
        text="Continue to workshop choices",
        fingerprint="continue",
    )
    assert not visible_phrase_present("Workshop choices", page(button))
    assert visible_phrase_present("Workshop choices", page(text("Workshop choices")))


def test_negative_status_does_not_prove_positive_effect() -> None:
    assert not visible_phrase_present("Work session saved", page(text("No work session saved.")))
    assert not visible_phrase_present(
        "Reservation submitted", page(text("Reservation not submitted."))
    )
    assert visible_phrase_present(
        "No reservation submitted", page(text("No reservation submitted."))
    )
    assert visible_phrase_present(
        "Work session saved", page(text("Work session saved for Monday."))
    )


async def test_static_plan_evidence_gets_one_bounded_correction() -> None:
    bad = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Complete release notes"],
        milestone_evidence={"Complete release notes": "visible_text:Draft release notes"},
    )
    good = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Complete release notes"],
        milestone_evidence={"Complete release notes": "verified_action:click:@mark_complete"},
    )
    provider = ScriptedReasoningProvider(bad, good)
    agent = LunaDecisionAgent(None, provider)
    decision = await agent.decide(
        page(text("Draft release notes")),
        TaskState(
            task="Complete the release checklist.",
            progress_signals=["verification_success"],
        ),
        WorkingMemory(),
    )
    assert len(provider.calls) == 2
    assert decision.milestone_evidence == good.milestone_evidence
    assert not decision.done
    assert "smaller observable milestone" in (provider.calls[1][0].failure_summary or "")
    assert "Do not invent future controls" in (provider.calls[1][0].failure_summary or "")


async def test_verified_action_allows_current_visible_milestone_plan_revision() -> None:
    milestone = "Record the selected model and its specifications."
    current_status = "Recorded Field 13: 16 GB memory, 256 GB storage."
    revised = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=[milestone],
        milestone_evidence={milestone: f"visible_text:{current_status}"},
    )
    provider = ScriptedReasoningProvider(revised)
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(
        task="Open product pages and record the selected model and specifications.",
        plan_initialized=True,
        milestones=[milestone],
        required_milestones=[milestone],
        milestone_evidence={milestone: "visible_text:Model recorded"},
        current_subgoal=milestone,
        progress_signals=["verification_success"],
    )

    decision = await agent.decide(page(text(current_status)), task, WorkingMemory())

    assert len(provider.calls) == 1
    assert provider.calls[0][0].purpose.value == "choose_action"
    assert decision.plan_initialized
    assert decision.replace_plan
    assert decision.milestone_evidence == {milestone: f"visible_text:{current_status}"}


async def test_one_enumerated_item_proof_does_not_complete_the_second_item() -> None:
    goal = 'Pin "Keyboard shortcuts" and "Screen reader labels" tickets.'
    first = "Pin the Keyboard shortcuts ticket."
    second = "Pin the Screen reader labels ticket."
    plan = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=[first, second],
        milestone_evidence={
            first: "visible_text:Pinned: Keyboard shortcuts",
            second: "visible_text:Pinned: Screen reader labels",
        },
    )
    provider = ScriptedReasoningProvider(plan)
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(task=goal)
    page_before_pinning = page(text("Nothing is pinned yet."))
    page_with_first_item_pinned = page(text("Pinned: Keyboard shortcuts"))

    decision = await agent.decide(page_before_pinning, task, WorkingMemory())
    task.plan_initialized = decision.plan_initialized is True
    task.milestones = decision.milestones
    task.required_milestones = decision.milestones
    task.milestone_evidence = decision.milestone_evidence
    task.current_subgoal = decision.current_subgoal

    completed = advance_observed_milestones(task, WorkingMemory(), page_with_first_item_pinned)

    assert len(provider.calls) == 1
    assert decision.milestones == [first, second]
    assert completed == [first]
    assert task.completed == [first]
    assert second not in task.completed


async def test_task_complete_proposal_preserves_initialized_required_milestones() -> None:
    first = "Open the workflow page."
    second = "Save the workflow."
    completion = ReasoningDecision(
        outcome=ReasoningOutcome.TASK_COMPLETE,
        milestones=[first, second],
        milestone_evidence={
            first: "visible_text:Workflow page",
            second: "visible_text:Workflow saved",
        },
    )
    provider = ScriptedReasoningProvider(completion)
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(
        task="Save the workflow.",
        plan_initialized=True,
        milestones=[first, second],
        required_milestones=[first, second],
        completed=[first],
        milestone_evidence=dict(completion.milestone_evidence),
        progress_signals=["verification_success"],
    )

    decision = await agent.decide(
        page(text("Workflow page\nWorkflow saved")), task, WorkingMemory()
    )

    assert decision.done
    assert decision.milestones == [first, second]
    assert decision.milestone_evidence == completion.milestone_evidence
    assert not decision.replace_plan


async def test_task_complete_requires_initialized_plan_and_verified_effect() -> None:
    milestone = "Save the workflow."
    completion = ReasoningDecision(
        outcome=ReasoningOutcome.TASK_COMPLETE,
        milestones=[milestone],
        milestone_evidence={milestone: "visible_text:Workflow saved"},
    )
    provider = ScriptedReasoningProvider(completion, completion)
    agent = LunaDecisionAgent(None, provider)

    for task in (
        TaskState(task="Save the workflow.", milestones=[milestone]),
        TaskState(
            task="Save the workflow.",
            plan_initialized=True,
            milestones=[milestone],
            required_milestones=[milestone],
        ),
    ):
        decision = await agent.decide(page(text("Workflow saved")), task, WorkingMemory())
        assert not decision.done
        assert decision.ask_user


async def test_static_plan_evidence_does_not_replan_without_remaining_call_budget() -> None:
    bad = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Complete release notes"],
        milestone_evidence={"Complete release notes": "visible_text:Draft release notes"},
    )
    good = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Complete release notes"],
        milestone_evidence={"Complete release notes": "verified_action:click:@mark_complete"},
    )
    provider = ScriptedReasoningProvider(bad, good)
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(task="Complete the release checklist.", llm_calls=1)
    task.set_reasoning_call_limit(1)

    decision = await agent.decide(page(text("Draft release notes")), task, WorkingMemory())

    assert len(provider.calls) == 1
    assert decision.ask_user
    assert agent.last_reasoning_calls == 1


async def test_repeated_static_plan_evidence_abstains_after_one_correction() -> None:
    bad = ReasoningDecision(
        outcome=ReasoningOutcome.MILESTONE_PLAN,
        milestones=["Complete release notes"],
        milestone_evidence={"Complete release notes": "visible_text:Draft release notes"},
    )
    provider = ScriptedReasoningProvider(bad)
    agent = LunaDecisionAgent(None, provider)
    decision = await agent.decide(
        page(text("Draft release notes")),
        TaskState(task="Complete the release checklist."),
        WorkingMemory(),
    )
    assert len(provider.calls) == 2
    assert decision.ask_user
    assert not decision.done
