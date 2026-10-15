"""Call-budget contracts for bounded, locally checkable browser tasks."""

from __future__ import annotations

from pathlib import Path

from browser_agent._types import (
    SemanticElement,
    SemanticSnapshot,
    TaskState,
    Viewport,
    WorkingMemory,
)
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningPurpose,
)


class ScriptedReasoningProvider:
    def __init__(self, *decisions: ReasoningDecision) -> None:
        self.decisions = list(decisions)
        self.calls: list[tuple[ReasoningContext, str, ReasoningEffort]] = []

    async def reason(
        self,
        context: ReasoningContext,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        self.calls.append((context, model, effort))
        index = min(len(self.calls) - 1, len(self.decisions) - 1)
        return self.decisions[index]


def snapshot(
    *,
    count: str = "0",
    saved: str | None = None,
    name_value: str = "",
) -> SemanticSnapshot:
    status_text = saved or f"Count: {count}"
    elements = [
        SemanticElement(
            ref="@increment",
            id=1,
            generation=1,
            role="button",
            accessible_name="Increment",
            interactable=True,
            fingerprint="increment-button",
        ),
        SemanticElement(
            ref="@status",
            id=2,
            generation=1,
            role="status",
            text=status_text,
            fingerprint="status-text",
        ),
        SemanticElement(
            ref="@name",
            id=3,
            generation=1,
            role="textbox",
            accessible_name="Name",
            value=name_value,
            interactable=True,
            fingerprint="name-field",
        ),
        SemanticElement(
            ref="@save",
            id=4,
            generation=1,
            role="button",
            accessible_name="Save",
            interactable=True,
            fingerprint="save-button",
        ),
    ]
    return SemanticSnapshot(
        url="https://fixture.test/task",
        title="Task fixture",
        active_tab="tab-task",
        tabs=["tab-task"],
        elements=elements,
        interactive_elements=[item for item in elements if item.interactable],
        state_generation=1,
        page_fingerprint="task-document",
        viewport=Viewport(width=1000, height=800),
    )


def task(goal: str, **updates: object) -> TaskState:
    values: dict[str, object] = {
        "task": goal,
        "user_goal": goal,
        "run_id": "microtask-call-budget",
        "plan_initialized": False,
    }
    values.update(updates)
    return TaskState.model_validate(values)


def memory(goal: str) -> WorkingMemory:
    return WorkingMemory(user_goal=goal)


async def test_verified_one_action_task_uses_one_luna_call_including_completion() -> None:
    goal = 'Click "Increment" exactly once. Finish when visible text contains "Count: 1".'
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="click", target_ref="@increment"),
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(snapshot(), task(goal), memory(goal))

    assert decision.action is not None
    assert decision.action.type == "click"
    assert decision.action.target is not None
    assert decision.action.target.ref == "@increment"
    assert decision.action.target.generation == 1
    assert len(provider.calls) == 1
    assert provider.calls[0][0].purpose == ReasoningPurpose.CHOOSE_ACTION
    assert provider.calls[0][0].candidate_options

    completed = await agent.decide(
        snapshot(count="1"),
        task(goal, steps_taken=1, progress_signals=["verification_success"]),
        memory(goal),
    )

    assert completed.done
    assert completed.action is None
    assert len(provider.calls) == 1


async def test_same_page_assignment_and_click_share_one_bounded_provider_call() -> None:
    goal = 'Fill "Name" with "Ada" and click "Save". Finish when visible text contains "Saved Ada".'
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            candidate_actions=[
                ReasoningAction(type="type", target_ref="@name", text="Ada"),
                ReasoningAction(type="click", target_ref="@save"),
            ],
        )
    )
    agent = LunaDecisionAgent(None, provider)

    first = await agent.decide(snapshot(), task(goal), memory(goal))

    assert first.action is not None
    assert first.action.type == "type"
    assert first.action.target is not None
    assert first.action.target.ref == "@name"
    assert first.action.text == "Ada"
    assert len(provider.calls) == 1
    assert provider.calls[0][0].purpose == ReasoningPurpose.CHOOSE_ACTION

    updated = await agent.decide(
        snapshot(name_value="Ada"),
        task(goal, steps_taken=1, progress_signals=["verification_success"]),
        memory(goal),
    )

    assert updated.action is not None
    assert updated.action.type == "click"
    assert updated.action.target is not None
    assert updated.action.target.ref == "@save"
    assert updated.action.target.generation == 1
    assert len(provider.calls) == 1


async def test_verified_action_does_not_complete_while_required_evidence_is_missing() -> None:
    goal = 'Fill "Name" with "Ada" and click "Save". Finish when visible text contains "Saved Ada".'
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="type", target_ref="@name", text="Ada"),
        ),
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="click", target_ref="@save"),
        ),
    )
    agent = LunaDecisionAgent(None, provider)

    first = await agent.decide(snapshot(), task(goal), memory(goal))
    assert first.action is not None

    still_incomplete = await agent.decide(
        snapshot(name_value="Ada"),
        task(
            goal,
            plan_initialized=True,
            milestones=["Saved name"],
            required_milestones=["Saved name"],
            milestone_evidence={"Saved name": "visible_text:Saved Ada"},
            completed=[],
            current_subgoal="Saved name",
            steps_taken=1,
            progress_signals=["verification_success"],
        ),
        memory(goal),
    )

    assert not still_incomplete.done
    assert still_incomplete.action is not None
    assert still_incomplete.action.type == "click"
    assert len(provider.calls) == 2


async def test_ambiguous_assignment_is_not_fast_pathed_into_an_action() -> None:
    goal = 'Fill "Name" with "Ada".'
    inputs = [
        SemanticElement(
            ref=ref,
            id=index,
            generation=1,
            role="textbox",
            accessible_name="Name",
            value="",
            interactable=True,
            fingerprint=f"name-{index}",
        )
        for index, ref in enumerate(("@name", "@billing-name"), start=1)
    ]
    ambiguous = SemanticSnapshot(
        url="https://fixture.test/form",
        title="Form",
        active_tab="tab-form",
        tabs=["tab-form"],
        elements=inputs,
        interactive_elements=inputs,
        state_generation=1,
        page_fingerprint="ambiguous-form",
        viewport=Viewport(width=1000, height=800),
    )
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.ASK_USER,
            questions=["Which Name field should I use?"],
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(ambiguous, task(goal), memory(goal))

    assert decision.ask_user == ["Which Name field should I use?"]
    assert decision.action is None
    assert len(provider.calls) == 1
    assert provider.calls[0][0].purpose == ReasoningPurpose.PLAN


async def test_long_multi_stage_task_keeps_initial_planning_call() -> None:
    goal = "Compare three listings across tabs, rank them by price, and prepare a shortlist."
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.MILESTONE_PLAN,
            milestones=["Find listings", "Compare prices", "Prepare shortlist"],
            milestone_evidence={
                "Find listings": "visible_text:Listings",
                "Compare prices": "visible_text:Price comparison",
                "Prepare shortlist": "visible_text:Shortlist ready",
            },
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(snapshot(), task(goal), memory(goal))

    assert decision.plan_initialized
    assert decision.milestones == ["Find listings", "Compare prices", "Prepare shortlist"]
    assert len(provider.calls) == 1
    assert provider.calls[0][0].purpose == ReasoningPurpose.PLAN


async def test_high_risk_microgoal_still_waits_for_explicit_confirmation(
    tmp_path: Path,
) -> None:
    from browser_agent.agent import AgentConfig, AgentRuntime
    from browser_agent.session import BrowserSession

    page = tmp_path / "order.html"
    page.write_text(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Order</title></head>
<body><h1 id="status">Review order</h1>
<form id="order"><button type="submit">Submit order</button></form>
<script>
document.querySelector('#order').addEventListener('submit', (event) => {
  event.preventDefault();
  document.querySelector('#status').textContent = 'Order submitted';
});
</script></body></html>""",
        encoding="utf-8",
    )
    goal = 'Submit the order. Finish when visible text contains "Order submitted".'
    provider = ScriptedReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="click", target_ref="@submit_order"),
        )
    )
    agent = LunaDecisionAgent(None, provider)

    async with BrowserSession.launch(headless=True) as browser:
        await browser.navigate(page.as_uri())
        async with AgentRuntime.open_sqlite(
            agent,
            browser,
            database=tmp_path / "microtask-confirmation.sqlite",
            config=AgentConfig(max_steps=3, max_llm_calls=3),
        ) as runtime:
            pending = await runtime.run(goal, run_id="microtask-high-risk")

            assert pending.status == "pending_confirmation"
            assert pending.run_id is not None
            assert len(provider.calls) == 1
            assert provider.calls[0][0].purpose == ReasoningPurpose.CHOOSE_ACTION
            confirmation = await runtime.pending_confirmation_details(pending.run_id)
            assert confirmation["target"] == "Submit order"
            assert "Review order" in ((await browser.observe()).text_excerpt or "")

            completed = await runtime.resume_with_confirmation(
                pending.run_id,
                approved=True,
            )
            final_snapshot = await browser.observe()

    assert completed.done
    assert completed.status == "completed"
    assert "Order submitted" in (final_snapshot.text_excerpt or "")
    assert len(provider.calls) == 1
