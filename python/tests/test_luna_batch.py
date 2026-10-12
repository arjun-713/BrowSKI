"""Luna reauthorizes each queued action after local verification."""

from __future__ import annotations

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
)

_GOAL = 'Fill "Full name" with "Ada"; fill "Email address" with "ada@example.test".'


class BatchProvider:
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


def form_snapshot(*, email_interactable: bool = True) -> SemanticSnapshot:
    return SemanticSnapshot(
        url="https://forms.example/profile",
        title="Profile",
        active_tab="tab-form",
        tabs=["tab-form"],
        state_generation=3,
        page_fingerprint="profile-page-v1",
        viewport=Viewport(width=1000, height=800),
        elements=[
            SemanticElement(
                ref="@name",
                id=1,
                generation=3,
                role="textbox",
                accessible_name="Full name",
                value="",
                fingerprint="name-fingerprint",
            ),
            SemanticElement(
                ref="@email",
                id=2,
                generation=3,
                role="textbox",
                accessible_name="Email address",
                value="",
                interactable=email_interactable,
                fingerprint="email-fingerprint",
            ),
        ],
    )


def batch_decision() -> ReasoningDecision:
    return ReasoningDecision(
        outcome=ReasoningOutcome.NEXT_ACTION,
        candidate_actions=[
            ReasoningAction(type="type", target_ref="@name", text="Ada"),
            ReasoningAction(
                type="type",
                target_ref="@email",
                text="ada@example.test",
            ),
        ],
    )


def task(*, verified: bool = False) -> TaskState:
    return TaskState(
        task=_GOAL,
        user_goal=_GOAL,
        plan_initialized=True,
        current_subgoal=_GOAL,
        run_id="run-luna-batch",
        progress_signals=["verification_success"] if verified else [],
    )


def set_value(snapshot: SemanticSnapshot, ref: str, value: str) -> None:
    element = snapshot.by_ref(ref)
    assert element is not None
    element.value = value


async def test_one_provider_call_executes_batch_with_current_candidate_reauthorization() -> None:
    provider = BatchProvider(batch_decision())
    agent = LunaDecisionAgent(None, provider)
    memory = WorkingMemory(user_goal=_GOAL)

    first = await agent.decide(form_snapshot(), task(), memory)

    assert first.action is not None
    assert first.action.type == "type"
    assert first.action.target is not None
    assert first.action.target.ref == "@name"
    assert len(provider.calls) == 1

    current = form_snapshot()
    set_value(current, "@name", "Ada")
    second = await agent.decide(current, task(verified=True), memory)

    assert second.action is not None
    assert second.action.type == "type"
    assert second.action.target is not None
    assert second.action.target.ref == "@email"
    assert len(provider.calls) == 1


async def test_batch_cancels_when_next_target_is_no_longer_a_current_candidate() -> None:
    provider = BatchProvider(batch_decision())
    agent = LunaDecisionAgent(None, provider)
    memory = WorkingMemory(user_goal=_GOAL)

    first = await agent.decide(form_snapshot(), task(), memory)
    assert first.action is not None

    current = form_snapshot(email_interactable=False)
    set_value(current, "@name", "Ada")
    result = await agent.decide(current, task(verified=True), memory)

    assert result.action is None
    assert result.ask_user
    assert len(provider.calls) == 2


async def test_explicit_queue_clear_requires_a_fresh_provider_decision() -> None:
    provider = BatchProvider(
        batch_decision(),
        ReasoningDecision(
            outcome=ReasoningOutcome.ASK_USER,
            questions=["Review the next step."],
        ),
    )
    agent = LunaDecisionAgent(None, provider)
    memory = WorkingMemory(user_goal=_GOAL)

    first = await agent.decide(form_snapshot(), task(), memory)
    assert first.action is not None
    agent.clear_browser_code_result()
    current = form_snapshot()
    set_value(current, "@name", "Ada")

    result = await agent.decide(current, task(verified=True), memory)

    assert result.ask_user == ["Review the next step."]
    assert result.action is None
    assert len(provider.calls) == 2
