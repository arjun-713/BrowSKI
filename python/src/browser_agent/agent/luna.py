"""Hybrid System One and GPT-6 Luna task decisions."""

from __future__ import annotations

from typing import Any

import structlog

from browser_agent._types import (
    AgentDecision,
    AgentObservation,
    BrowserAction,
    ElementRef,
    PrunedElement,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.runtime import Agent
from browser_agent.decisions import (
    ActionCandidate,
    CandidateKind,
    CandidatePolicy,
    DecisionProvider,
    DecisionProviderError,
    build_action_candidates,
    select_action_candidate,
)
from browser_agent.progress.task_state import check_completion
from browser_agent.reasoning import (
    ComplexityGate,
    ComplexityResult,
    ComplexitySignals,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningProvider,
    ReasoningPurpose,
    configured_luna_model,
)

_logger: Any = structlog.get_logger("browser_agent.agent.luna")


class LunaDecisionAgent(Agent):
    """Use bounded System One choices first and Luna for unresolved planning."""

    def __init__(
        self,
        decision_provider: DecisionProvider,
        reasoning_provider: ReasoningProvider | None,
        *,
        model: str | None = None,
        candidate_policy: CandidatePolicy | None = None,
        complexity_gate: ComplexityGate | None = None,
    ) -> None:
        self.decision_provider = decision_provider
        self.reasoning_provider = reasoning_provider
        self.model = configured_luna_model() if model is None else model
        self.candidate_policy = candidate_policy or CandidatePolicy()
        self.complexity_gate = complexity_gate or ComplexityGate()

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        observation = _agent_observation(snapshot)
        if "verification_success" in task.progress_signals and check_completion(
            task,
            snapshot,
            verified_action=True,
        ):
            return AgentDecision(
                done=True,
                result_summary="Task completion is supported by verified browser evidence.",
            )

        if not task.plan_initialized:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.PLAN,
            )

        last_recovery = task.recovery_history[-1] if task.recovery_history else {}
        recovery_step = str(last_recovery.get("step", ""))
        if task.recovery_streak > 0 and recovery_step in {
            "luna_normal_replan",
            "luna_high_replan",
        }:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.REPLAN,
                failure_summary=str(last_recovery.get("reason", "Recovery requested a replan.")),
            )

        candidates = build_action_candidates(
            task.user_goal or task.task,
            task.current_subgoal or task.next_milestone or task.task,
            observation,
            {"click", "check", "scroll", "type", "select"},
            self.candidate_policy,
        )
        try:
            selected = await select_action_candidate(
                self.decision_provider,
                task=task.user_goal or task.task,
                current_subgoal=task.current_subgoal or task.task,
                observation=observation,
                candidates=candidates,
                run_id=task.run_id,
                step_id=task.steps_taken + 1,
            )
        except DecisionProviderError as exc:
            _logger.warning(
                "system_one_decision_failed",
                error_type=type(exc).__name__,
            )
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.RESOLVE_AMBIGUITY,
                failure_summary=f"System One decision failed: {type(exc).__name__}.",
            )

        if selected.kind == CandidateKind.ESCALATE_TO_PLANNER:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.RESOLVE_AMBIGUITY,
                failure_summary="System One selected its planner escalation candidate.",
            )

        try:
            action = selected.to_browser_action(_resolve_target(selected, snapshot))
        except ValueError as exc:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.RESOLVE_AMBIGUITY,
                failure_summary=f"Selected target could not be bound: {type(exc).__name__}.",
            )
        if action is None:
            return AgentDecision(ask_user=["The selected browser action could not be grounded."])
        return AgentDecision(action=action, reasoning="Selected from bounded System One choices.")

    def complexity_for_recovery(
        self,
        task: TaskState,
        snapshot: SemanticSnapshot,
        *,
        normal_replan_failed: bool = False,
    ) -> ComplexityResult:
        history = task.recovery_history
        repeated_uncertainty = sum(
            1
            for event in history
            if str(event.get("classification", "")).casefold()
            in {"uncertain", "provider_abstained"}
        )
        ambiguous_failures = sum(
            1 for event in history if "AMBIGUOUS" in str(event.get("reason", "")).upper()
        )
        active_subgoals = max(1, len(task.milestones) - len(task.completed))
        goal_text = (task.user_goal or task.task).casefold()
        cross_tab_required = any(
            phrase in goal_text for phrase in ("across tabs", "multiple tabs", "each tab")
        )
        signals = ComplexitySignals(
            recovery_count=task.recovery_streak,
            replan_count=task.replan_count,
            uncertain_verification_count=repeated_uncertainty,
            active_subgoal_count=active_subgoals,
            semantic_ambiguity_count=ambiguous_failures,
            tab_count=max(1, len(snapshot.tabs)),
            cross_tab_synthesis_required=cross_tab_required,
            normal_replan_failed=normal_replan_failed,
        )
        return self.complexity_gate.evaluate(signals)

    async def _ask_luna(
        self,
        observation: AgentObservation,
        task: TaskState,
        memory: WorkingMemory,
        *,
        snapshot: SemanticSnapshot,
        purpose: ReasoningPurpose,
        failure_summary: str | None = None,
    ) -> AgentDecision:
        provider = self.reasoning_provider
        if provider is None:
            return AgentDecision(
                ask_user=[
                    "The bounded local decision provider could not choose an action, "
                    "and no Luna reasoning provider is configured."
                ]
            )

        gate_result = self.complexity_for_recovery(task, snapshot)
        effort = gate_result.effort
        if purpose == ReasoningPurpose.REPLAN and task.recovery_history:
            latest_recovery_step = task.recovery_history[-1].get("step")
            if latest_recovery_step == "luna_normal_replan":
                effort = ReasoningEffort.LOW
            elif latest_recovery_step == "luna_high_replan":
                effort = ReasoningEffort.HIGH
        context = ReasoningContext(
            purpose=purpose,
            task=task,
            memory=memory,
            observation=observation,
            prior_summary=memory.checkpoint_summary or "",
            failure_summary=failure_summary,
        )
        try:
            # Provider implementations can cross an untyped SDK/plugin boundary.
            result: Any = await provider.reason(context, model=self.model, effort=effort)
            if not isinstance(result, ReasoningDecision):
                raise TypeError("reasoning provider returned an invalid decision")
        except Exception as exc:
            _logger.warning(
                "reasoning_provider_failed",
                provider="openai",
                error_type=type(exc).__name__,
                effort=effort.value,
            )
            return AgentDecision(
                ask_user=[
                    "Luna reasoning was unavailable. Review the current browser state "
                    "and provide guidance before continuing."
                ],
                reasoning_effort=effort.value,
            )

        reasoning = result.summary[:2_000]
        if result.outcome == ReasoningOutcome.ASK_USER:
            return AgentDecision(
                ask_user=result.questions,
                reasoning=reasoning,
                reasoning_effort=effort.value,
            )
        if result.outcome == ReasoningOutcome.MILESTONE_PLAN:
            return AgentDecision(
                milestones=result.milestones,
                milestone_evidence=result.milestone_evidence,
                plan_initialized=True,
                current_subgoal=result.current_subgoal or result.milestones[0],
                next_milestone=(result.milestones[1] if len(result.milestones) > 1 else None),
                reasoning=reasoning,
                reasoning_effort=effort.value,
                replace_plan=purpose == ReasoningPurpose.REPLAN,
            )
        if result.outcome == ReasoningOutcome.INTERPRETATION:
            return AgentDecision(
                ask_user=[reasoning or "The current page state needs user interpretation."],
                reasoning=reasoning,
                reasoning_effort=effort.value,
            )

        try:
            actions = result.bind_actions(observation)
        except ValueError as exc:
            return AgentDecision(
                ask_user=[
                    "Luna proposed a target that is not available in the current "
                    "semantic observation. Please review the page."
                ],
                reasoning=f"Unbound semantic action: {type(exc).__name__}.",
                reasoning_effort=effort.value,
            )

        action = (
            actions[0]
            if result.action is not None
            else await self._choose_luna_candidate(
                actions,
                result.candidate_actions,
                task,
                observation,
            )
        )
        if action is None:
            return AgentDecision(
                ask_user=["System One abstained from Luna's bounded action candidates."],
                reasoning=reasoning,
                reasoning_effort=effort.value,
            )
        return AgentDecision(
            milestones=result.milestones,
            milestone_evidence=result.milestone_evidence,
            plan_initialized=True,
            current_subgoal=result.current_subgoal or task.current_subgoal,
            replace_plan=purpose == ReasoningPurpose.REPLAN and bool(result.milestones),
            action=action,
            reasoning=reasoning,
            reasoning_effort=effort.value,
        )

    async def _choose_luna_candidate(
        self,
        actions: list[BrowserAction],
        candidates: list[Any],
        task: TaskState,
        observation: AgentObservation,
    ) -> BrowserAction | None:
        if len(actions) != len(candidates) or not actions:
            return None
        options = {
            f"c{index:02d}": _action_description(candidate)
            for index, candidate in enumerate(candidates, start=1)
        }
        try:
            answer = await self.decision_provider.choose(
                {
                    "task": task.user_goal or task.task,
                    "current_subgoal": task.current_subgoal,
                    "run_id": task.run_id,
                    "steps_taken": task.steps_taken + 1,
                    "observation": observation.model_dump(mode="json", exclude={"elements"}),
                    "candidates": options,
                },
                "Choose one supplied Luna action candidate. Do not create a new action.",
                options,
            )
        except DecisionProviderError:
            return None
        if answer.accepted is not True:
            return None
        selected_id = str(answer.value)
        index = int(selected_id[1:]) - 1 if selected_id.startswith("c") else -1
        if index < 0 or index >= len(actions) or selected_id not in options:
            return None
        return actions[index]


def _agent_observation(snapshot: SemanticSnapshot) -> AgentObservation:
    elements = [
        PrunedElement(
            ref=element.ref,
            role=element.role,
            name=element.accessible_name,
            text=element.text,
            value=None,
            state=element.state,
            interactable=element.interactable and element.visible and element.enabled,
        )
        for element in snapshot.elements
    ]
    return AgentObservation(
        url=snapshot.url,
        title=snapshot.title,
        active_tab=snapshot.active_tab,
        state_generation=snapshot.state_generation,
        page_fingerprint=snapshot.page_fingerprint,
        elements=elements,
        focused=snapshot.focused,
    )


def _resolve_target(
    candidate: ActionCandidate,
    snapshot: SemanticSnapshot,
) -> ElementRef | None:
    if candidate.target_ref is None:
        return None
    element = snapshot.by_ref(candidate.target_ref)
    if element is None or not element.interactable or not element.visible or not element.enabled:
        return None
    return ElementRef(
        ref=element.ref,
        id=element.id,
        generation=snapshot.state_generation,
    )


def _action_description(action: Any) -> str:
    target = getattr(action, "target_ref", None)
    action_type = getattr(action, "type", "unknown")
    return f"{action_type} action" + (f" on {target}" if target else "")
