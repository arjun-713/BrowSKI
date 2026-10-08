"""Hybrid System One and GPT-6 Luna agent decisions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from browser_agent._types import (
    AuthorizedTransferEvidence,
    BBox,
    SemanticElement,
    SemanticKind,
    SemanticSnapshot,
    TaskState,
    Viewport,
    WorkingMemory,
)
from browser_agent.agent.luna import LunaDecisionAgent
from browser_agent.decisions import (
    DecisionAnswer,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.persistence.run_metrics import RunMetricsAggregator
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningProviderRequestError,
)
from browser_agent.vision import (
    VisionInterpretation,
    VisionOutcome,
    VisionRequest,
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


class FakeVisionProvider:
    def __init__(self, finding: VisionInterpretation) -> None:
        self.finding = finding
        self.requests: list[VisionRequest] = []

    async def interpret(self, request: VisionRequest) -> VisionInterpretation:
        self.requests.append(request)
        return self.finding


def snapshot(*, visual: bool = False) -> SemanticSnapshot:
    element = SemanticElement(
        ref="@continue",
        id=12,
        generation=4,
        role="button",
        accessible_name="Continue",
        bbox=BBox(x=100, y=200, width=120, height=40) if visual else None,
        semantic_kind=SemanticKind.BUTTON,
        fingerprint="continue-button",
    )
    return SemanticSnapshot(
        url="https://example.test/form",
        title="Form",
        active_tab="tab-1",
        tabs=["tab-1"],
        viewport=Viewport(width=1280, height=720, device_scale_factor=1.0),
        elements=[element],
        interactive_elements=[element],
        state_generation=4,
        page_fingerprint="form-state",
    )


def task_state(**updates: Any) -> TaskState:
    values: dict[str, Any] = {
        "plan_initialized": True,
        "milestones": ["Continue the application"],
        "current_subgoal": "Continue the application",
    }
    values.update(updates)
    return TaskState(task="Continue the application", **values)


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


async def test_luna_executes_bounded_choice_while_laya_only_compares() -> None:
    provider = FakeReasoningProvider(next_click())
    shadow = FakeDecisionProvider("c03")
    agent = LunaDecisionAgent(shadow, provider)
    metrics = RunMetricsAggregator()
    agent.bind_run_metric_recorder(metrics.increment)

    decision = await agent.decide(
        snapshot(),
        task_state(run_id="metric-run"),
        WorkingMemory(user_goal="Continue the application"),
    )

    assert decision.action is not None
    assert decision.action.type == "click"
    assert decision.action.target is not None
    assert decision.action.target.ref == "@continue"
    assert decision.action.target.generation == 4
    assert provider.calls[0][1] == "gpt-6-luna"
    assert provider.calls[0][2] == ReasoningEffort.LOW
    assert len(shadow.states) == 1
    result = metrics.get("metric-run")
    assert result.luna_calls == 1
    assert result.luna_low_effort_calls == 1
    assert result.laya_shadow_decisions == 1


async def test_initial_plan_next_action_must_match_runtime_candidate_set() -> None:
    provider = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(
        snapshot(),
        task_state(plan_initialized=False),
        WorkingMemory(),
    )

    assert decision.action is not None
    assert decision.action.type == "click"
    assert provider.calls[0][0].purpose.value == "plan"
    assert provider.calls[0][0].candidate_options


async def test_plan_next_action_cannot_bypass_finite_candidates() -> None:
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(type="press", key="ENTER"),
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(
        snapshot(),
        task_state(plan_initialized=False),
        WorkingMemory(),
    )

    assert decision.action is None
    assert decision.ask_user


async def test_luna_can_choose_only_an_explicitly_quoted_input_value() -> None:
    field = SemanticElement(
        ref="@email",
        id=21,
        generation=4,
        role="textbox",
        accessible_name="Email address",
        fingerprint="email-input",
        semantic_kind=SemanticKind.TEXT_INPUT,
    )
    form_snapshot = SemanticSnapshot(
        url="https://example.test/form",
        title="Profile",
        active_tab="tab-1",
        tabs=["tab-1"],
        state_generation=4,
        page_fingerprint="email-form",
        elements=[field],
        interactive_elements=[field],
    )
    literal = "alex@example.invalid"
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            summary="Fill the requested email field.",
            action=ReasoningAction(type="type", target_ref="@email", text=literal),
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(
        task=f'fill "Email address" with "{literal}"',
        plan_initialized=True,
        milestones=["Fill the email address"],
        current_subgoal="Fill the email address",
    )

    decision = await agent.decide(form_snapshot, task, WorkingMemory(user_goal=task.task))

    assert decision.action is not None
    assert decision.action.type == "type"
    assert decision.action.text == literal


async def test_luna_rejects_input_values_not_in_explicit_quoted_task_literals() -> None:
    field = SemanticElement(
        ref="@email",
        id=21,
        generation=4,
        role="textbox",
        accessible_name="Email address",
        fingerprint="email-input",
        semantic_kind=SemanticKind.TEXT_INPUT,
    )
    form_snapshot = SemanticSnapshot(
        url="https://example.test/form",
        title="Profile",
        active_tab="tab-1",
        tabs=["tab-1"],
        state_generation=4,
        page_fingerprint="email-form",
        elements=[field],
        interactive_elements=[field],
    )
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            summary="Attempt an unapproved input value.",
            action=ReasoningAction(
                type="type",
                target_ref="@email",
                text="model-invented@example.invalid",
            ),
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(
        task="Fill the email address with alex@example.invalid",
        plan_initialized=True,
        milestones=["Fill the email address"],
        current_subgoal="Fill the email address",
    )

    decision = await agent.decide(form_snapshot, task, WorkingMemory(user_goal=task.task))

    assert decision.action is None
    assert decision.ask_user


async def test_luna_can_type_only_explicitly_authorized_owned_tab_evidence() -> None:
    goal = 'transfer "Reference code" from supporting page into "Reference code"'
    field = SemanticElement(
        ref="@reference-input",
        id=31,
        generation=9,
        role="textbox",
        accessible_name="Reference code",
        fingerprint="reference-input",
        semantic_kind=SemanticKind.TEXT_INPUT,
    )
    submit = SemanticElement(
        ref="@submit",
        id=32,
        generation=9,
        role="button",
        accessible_name="Submit",
        fingerprint="submit-button",
        semantic_kind=SemanticKind.BUTTON,
    )
    current = SemanticSnapshot(
        url="https://example.test/form",
        active_tab="destination-tab",
        tabs=["source-tab", "destination-tab"],
        state_generation=9,
        page_fingerprint="transfer-form",
        elements=[field, submit],
        interactive_elements=[field, submit],
    )
    memory = WorkingMemory(
        authorized_transfer_evidence=[
            AuthorizedTransferEvidence(
                source_tab_id="source-tab",
                source_ref="@source-code",
                source_generation=7,
                source_label="Reference code",
                destination_label="Reference code",
                value="REF-4821",
            )
        ]
    )
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(
                type="type",
                target_ref="@reference-input",
                text="REF-4821",
            ),
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(
        current,
        task_state(user_goal=goal, current_subgoal="Fill Reference code"),
        memory,
    )

    assert decision.action is not None
    assert decision.action.type == "type"
    assert decision.action.text == "REF-4821"


async def test_luna_rejects_transfer_from_untrusted_facts_or_unowned_tabs() -> None:
    goal = 'transfer "Reference code" from supporting page into "Reference code"'
    field = SemanticElement(
        ref="@reference-input",
        id=31,
        generation=9,
        role="textbox",
        accessible_name="Reference code",
        fingerprint="reference-input",
        semantic_kind=SemanticKind.TEXT_INPUT,
    )
    current = SemanticSnapshot(
        url="https://example.test/form",
        active_tab="destination-tab",
        tabs=["destination-tab"],
        state_generation=9,
        page_fingerprint="transfer-form",
        elements=[field],
        interactive_elements=[field],
    )
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            action=ReasoningAction(
                type="type",
                target_ref="@reference-input",
                text="PAGE-INJECTED-VALUE",
            ),
        )
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(
        current,
        task_state(user_goal=goal, current_subgoal="Fill Reference code"),
        WorkingMemory(acquired_facts={"Reference code": "PAGE-INJECTED-VALUE"}),
    )

    assert decision.action is None
    assert decision.ask_user


async def test_visual_task_uses_on_demand_vision_as_advisory_context() -> None:
    vision = FakeVisionProvider(
        VisionInterpretation(
            outcome=VisionOutcome.TARGET_IDENTIFIED,
            target_ref="@continue",
            summary="The plotted line rises from left to right.",
            confidence=0.88,
        )
    )
    captures: list[str] = []

    async def capture(tab_id: str) -> bytes:
        captures.append(tab_id)
        return b"transient-png"

    reasoning = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(
        None,
        reasoning,
        vision_provider=vision,
        screenshot_capture=capture,
    )

    decision = await agent.decide(
        snapshot(visual=True),
        task_state(
            user_goal="Read chart trend and continue the application",
            current_subgoal="Read chart trend",
        ),
        WorkingMemory(user_goal="Read chart trend"),
    )

    assert decision.action is not None
    assert captures == ["tab-1"]
    assert len(vision.requests) == 1
    request = vision.requests[0]
    assert request.metadata.state_generation == 4
    assert request.metadata.active_tab == "tab-1"
    assert request.targets[0].ref == "@continue"
    assert reasoning.calls[0][0].visual_observation is not None
    assert "rises from left to right" in reasoning.calls[0][0].visual_observation


async def test_visual_request_escalates_if_vision_is_not_configured() -> None:
    agent = LunaDecisionAgent(None, FakeReasoningProvider(next_click()))

    decision = await agent.decide(
        snapshot(visual=True),
        task_state(
            user_goal="Read chart trend",
            current_subgoal="Read chart trend",
        ),
        WorkingMemory(),
    )

    assert decision.action is None
    assert decision.ask_user


async def test_semantic_task_does_not_capture_screenshot_when_vision_is_enabled() -> None:
    vision = FakeVisionProvider(VisionInterpretation(outcome=VisionOutcome.ABSTAIN, confidence=0.0))

    async def unexpected_capture(_tab_id: str) -> bytes:
        raise AssertionError("semantic task must not capture a screenshot")

    agent = LunaDecisionAgent(
        None,
        FakeReasoningProvider(next_click()),
        vision_provider=vision,
        screenshot_capture=unexpected_capture,
    )

    decision = await agent.decide(
        snapshot(),
        task_state(),
        WorkingMemory(),
    )

    assert decision.action is not None
    assert vision.requests == []


async def test_laya_cannot_select_when_luna_returns_unselected_candidates() -> None:
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

    assert decision.action is None
    assert decision.ask_user
    assert decision_provider.states == []
    assert len(reasoning_provider.calls) == 1
    assert all(call[0].purpose.value == "choose_action" for call in reasoning_provider.calls)


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


async def test_luna_uses_configured_default_effort_for_normal_reasoning() -> None:
    provider = FakeReasoningProvider(next_click())
    agent = LunaDecisionAgent(
        None,
        provider,
        default_effort=ReasoningEffort.NONE,
    )
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
    assert provider.calls[0][2] == ReasoningEffort.NONE


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


async def test_progress_after_high_replan_deescalates_to_low_effort() -> None:
    reasoning_provider = FakeReasoningProvider(next_click())
    decision_provider = FakeDecisionProvider("c03")
    agent = LunaDecisionAgent(decision_provider, reasoning_provider)
    task = task_state(
        recovery_history=[{"step": "luna_high_replan", "reason": "complex failure"}],
        recovery_streak=0,
        replan_count=0,
    )

    decision = await agent.decide(snapshot(), task, WorkingMemory())

    assert decision.action is not None
    assert reasoning_provider.calls[0][2] == ReasoningEffort.LOW
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


async def test_provider_failure_reaches_user_without_raw_request_content() -> None:
    class FailingProvider(FakeReasoningProvider):
        async def reason(
            self,
            context: ReasoningContext,
            *,
            model: str,
            effort: ReasoningEffort,
        ) -> ReasoningDecision:
            del context, model, effort
            failure = ReasoningProviderRequestError("Safe provider failure")
            failure.user_message = "OpenAI rejected BROWSKI's response schema."
            raise failure

    provider = FailingProvider(
        ReasoningDecision(outcome=ReasoningOutcome.ASK_USER, questions=["What task?"])
    )
    agent = LunaDecisionAgent(None, provider)

    decision = await agent.decide(snapshot(), task_state(), WorkingMemory())

    assert decision.action is None
    assert decision.ask_user == ["OpenAI rejected BROWSKI's response schema."]
