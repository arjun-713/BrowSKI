"""GPT-6 Luna decisions with non-executing System One shadow comparison."""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
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
    CandidatePolicy,
    DecisionProvider,
    build_action_candidates,
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
from browser_agent.vision import (
    ScreenshotMetadata,
    SemanticTargetMetadata,
    VisionInterpretation,
    VisionProvider,
    VisionRequest,
    interpret_if_semantics_insufficient,
)

_logger: Any = structlog.get_logger("browser_agent.agent.luna")
_VISUAL_CUES = frozenset(
    {
        "chart",
        "graph",
        "diagram",
        "image",
        "photo",
        "picture",
        "canvas",
        "visual",
        "icon",
        "layout",
        "color",
        "colour",
        "red",
        "blue",
        "green",
        "yellow",
        "orange",
        "purple",
    }
)
_VISUAL_CONTENT_TASKS = frozenset(
    {"read", "interpret", "summarize", "compare", "trend", "identify", "describe"}
)


class LunaDecisionAgent(Agent):
    """Use Luna for executable choices and System One only as a shadow."""

    def __init__(
        self,
        decision_provider: DecisionProvider | None,
        reasoning_provider: ReasoningProvider | None,
        *,
        model: str | None = None,
        candidate_policy: CandidatePolicy | None = None,
        complexity_gate: ComplexityGate | None = None,
        vision_provider: VisionProvider | None = None,
        screenshot_capture: Callable[[str], Awaitable[bytes]] | None = None,
    ) -> None:
        self.decision_provider = decision_provider
        self.reasoning_provider = reasoning_provider
        self.model = configured_luna_model() if model is None else model
        self.candidate_policy = candidate_policy or CandidatePolicy()
        self.complexity_gate = complexity_gate or ComplexityGate()
        self.vision_provider = vision_provider
        self.screenshot_capture = screenshot_capture
        self._vision_cache: dict[str, VisionInterpretation] = {}

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
        visual_context = await self._visual_context(snapshot, task, observation)
        if isinstance(visual_context, AgentDecision):
            return visual_context

        if not task.plan_initialized:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.PLAN,
                visual_context=visual_context,
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
                visual_context=visual_context,
            )

        candidates = build_action_candidates(
            task.user_goal or task.task,
            task.current_subgoal or task.next_milestone or task.task,
            observation,
            {"click", "check", "scroll", "type", "select"},
            self.candidate_policy,
        )
        options = {
            f"c{index:02d}": candidate.description
            for index, candidate in enumerate(candidates, start=1)
        }
        return await self._ask_luna(
            observation,
            task,
            memory,
            snapshot=snapshot,
            purpose=ReasoningPurpose.CHOOSE_ACTION,
            candidate_options=options,
            bounded_candidates=candidates,
            visual_context=visual_context,
        )

    async def _visual_context(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        observation: AgentObservation,
    ) -> str | AgentDecision | None:
        if not _visual_semantics_insufficient(task, observation):
            return None
        if (
            self.reasoning_provider is None
            or self.vision_provider is None
            or self.screenshot_capture is None
        ):
            return AgentDecision(
                ask_user=[
                    "This task needs visual page information, but on-demand vision "
                    "is disabled or unavailable. Enable standard-mode vision or "
                    "provide guidance."
                ]
            )

        cache_key = f"{snapshot.page_fingerprint}:{snapshot.state_generation}"
        cached = self._vision_cache.get(cache_key)
        if cached is None:
            tab_id = snapshot.active_tab
            if not tab_id:
                return AgentDecision(ask_user=["Vision could not identify the active browser tab."])
            try:
                screenshot = await self.screenshot_capture(tab_id)
                request = _vision_request(
                    task=task.user_goal or task.task,
                    snapshot=snapshot,
                    observation=observation,
                    screenshot=screenshot,
                )
                finding = await interpret_if_semantics_insufficient(
                    self.vision_provider,
                    lambda: request,
                    semantic_sufficient=False,
                )
            except Exception as exc:
                _logger.warning(
                    "vision_interpretation_failed",
                    run_id=task.run_id,
                    error_type=type(exc).__name__,
                )
                return AgentDecision(
                    ask_user=[
                        "The required visual page interpretation was unavailable; review the page."
                    ]
                )
            if finding is None or finding.outcome.value == "abstain":
                return AgentDecision(
                    ask_user=[
                        "Visual inspection could not resolve the task safely; review the page."
                    ]
                )
            self._vision_cache[cache_key] = finding
            if len(self._vision_cache) > 4:
                self._vision_cache.pop(next(iter(self._vision_cache)))
            cached = finding

        if cached.outcome.value == "abstain":
            return AgentDecision(ask_user=["Visual inspection abstained; review the page."])
        target_note = (
            f"Grounded semantic target: {cached.target_ref}. " if cached.target_ref else ""
        )
        summary = cached.summary.strip()
        if not summary and not target_note:
            return AgentDecision(ask_user=["Visual inspection returned no usable finding."])
        return (target_note + summary)[:1_200]

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
        candidate_options: dict[str, str] | None = None,
        bounded_candidates: list[ActionCandidate] | None = None,
        visual_context: str | None = None,
    ) -> AgentDecision:
        provider = self.reasoning_provider
        if provider is None:
            return AgentDecision(
                ask_user=[
                    "GPT-6 Luna is not configured. Configure its provider or "
                    "provide user guidance before continuing."
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
            visual_observation=visual_context,
            failure_summary=failure_summary,
            candidate_options=candidate_options or {},
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

        if purpose == ReasoningPurpose.CHOOSE_ACTION:
            return await self._bounded_luna_action(
                result,
                observation=observation,
                snapshot=snapshot,
                task=task,
                candidates=bounded_candidates or [],
                options=candidate_options or {},
                reasoning=reasoning,
                effort=effort,
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
                memory,
                observation,
                prior_summary=memory.checkpoint_summary or "",
                visual_observation=visual_context,
                failure_summary=failure_summary,
                effort=effort,
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

    async def _bounded_luna_action(
        self,
        result: ReasoningDecision,
        *,
        observation: AgentObservation,
        snapshot: SemanticSnapshot,
        task: TaskState,
        candidates: list[ActionCandidate],
        options: dict[str, str],
        reasoning: str,
        effort: ReasoningEffort,
    ) -> AgentDecision:
        if result.outcome != ReasoningOutcome.NEXT_ACTION or result.action is None:
            return AgentDecision(
                ask_user=["Luna could not select one of the bounded browser actions."],
                reasoning=reasoning,
                reasoning_effort=effort.value,
            )
        try:
            proposed = result.action.bind(observation)
        except ValueError:
            proposed = None

        chosen_candidate: ActionCandidate | None = None
        action: BrowserAction | None = None
        if proposed is not None:
            for candidate in candidates:
                try:
                    candidate_action = candidate.to_browser_action(
                        _resolve_target(candidate, snapshot)
                    )
                except ValueError:
                    continue
                if candidate_action is None:
                    continue
                if _action_signature(candidate_action) == _action_signature(proposed):
                    chosen_candidate = candidate
                    action = candidate_action
                    break

        luna_id = next(
            (
                candidate_id
                for index, candidate_id in enumerate(options)
                if candidates[index] is chosen_candidate
            ),
            None,
        )
        if action is None:
            return AgentDecision(
                ask_user=["Luna proposed an action outside the bounded candidate set."],
                reasoning="The proposed action did not match an available candidate.",
                reasoning_effort=effort.value,
            )

        if self.decision_provider is None:
            return AgentDecision(
                action=action,
                reasoning=reasoning or "Selected by GPT-6 Luna from bounded semantic actions.",
                reasoning_effort=effort.value,
            )

        shadow_started = time.perf_counter()
        try:
            shadow = await self.decision_provider.choose(
                {
                    "task": task.user_goal or task.task,
                    "current_subgoal": task.current_subgoal or task.task,
                    "run_id": task.run_id,
                    "steps_taken": task.steps_taken + 1,
                    "observation": observation.model_dump(mode="json", exclude={"elements"}),
                    "candidates": options,
                },
                "Choose one supplied candidate for shadow comparison only. "
                "Do not create an action.",
                options,
            )
            shadow_id = str(shadow.value) if shadow.accepted is True else None
            _logger.info(
                "laya_shadow_comparison",
                run_id=task.run_id,
                step=task.steps_taken + 1,
                laya_choice=shadow_id if shadow_id in options else None,
                luna_choice=luna_id,
                agreement=(shadow_id == luna_id) if shadow_id in options else None,
                confidence=shadow.confidence_calibrated,
                elapsed_ms=round((time.perf_counter() - shadow_started) * 1000, 3),
            )
        except Exception as exc:
            _logger.warning(
                "laya_shadow_comparison_failed",
                run_id=task.run_id,
                step=task.steps_taken + 1,
                error_type=type(exc).__name__,
            )
        return AgentDecision(
            action=action,
            reasoning=reasoning or "Selected by GPT-6 Luna from bounded semantic actions.",
            reasoning_effort=effort.value,
        )

    async def _choose_luna_candidate(
        self,
        actions: list[BrowserAction],
        candidates: list[Any],
        task: TaskState,
        memory: WorkingMemory,
        observation: AgentObservation,
        *,
        prior_summary: str,
        visual_observation: str | None,
        failure_summary: str | None,
        effort: ReasoningEffort,
    ) -> BrowserAction | None:
        if len(actions) != len(candidates) or not actions or self.reasoning_provider is None:
            return None
        options = {
            f"c{index:02d}": _action_description(candidate)
            for index, candidate in enumerate(candidates, start=1)
        }
        context = ReasoningContext(
            purpose=ReasoningPurpose.CHOOSE_ACTION,
            task=task,
            memory=memory,
            observation=observation,
            prior_summary=prior_summary,
            visual_observation=visual_observation,
            failure_summary=failure_summary,
            candidate_options=options,
        )
        started = time.perf_counter()
        try:
            luna_result = await self.reasoning_provider.reason(
                context,
                model=self.model,
                effort=effort,
            )
        except Exception as exc:
            _logger.warning(
                "luna_action_choice_failed",
                error_type=type(exc).__name__,
                run_id=task.run_id,
                step=task.steps_taken + 1,
            )
            return None

        selected_action: BrowserAction | None = None
        if luna_result.outcome == ReasoningOutcome.NEXT_ACTION and luna_result.action is not None:
            try:
                proposed = luna_result.action.bind(observation)
            except ValueError:
                proposed = None
            if proposed is not None:
                selected_action = next(
                    (
                        action
                        for action in actions
                        if action.model_dump(mode="json", exclude_none=True)
                        == proposed.model_dump(mode="json", exclude_none=True)
                    ),
                    None,
                )
        selected_id = next(
            (
                candidate_id
                for index, candidate_id in enumerate(options)
                if actions[index] is selected_action
            ),
            None,
        )
        elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
        _logger.info(
            "luna_action_choice",
            run_id=task.run_id,
            step=task.steps_taken + 1,
            selected_candidate=selected_id,
            outcome=luna_result.outcome.value,
            elapsed_ms=round(elapsed_ms, 3),
        )
        if selected_action is None:
            return None

        # The bounded provider is observational only. Its result is recorded for
        # comparison and never changes the action selected by Luna.
        if self.decision_provider is None:
            return selected_action

        shadow_started = time.perf_counter()
        try:
            shadow_answer = await self.decision_provider.choose(
                {
                    "task": task.user_goal or task.task,
                    "current_subgoal": task.current_subgoal,
                    "run_id": task.run_id,
                    "steps_taken": task.steps_taken + 1,
                    "observation": observation.model_dump(mode="json", exclude={"elements"}),
                    "candidates": options,
                },
                "Choose one supplied candidate for shadow comparison only. "
                "Do not create an action.",
                options,
            )
            shadow_id = str(shadow_answer.value) if shadow_answer.accepted is True else None
            _logger.info(
                "laya_shadow_comparison",
                run_id=task.run_id,
                step=task.steps_taken + 1,
                laya_choice=shadow_id if shadow_id in options else None,
                luna_choice=selected_id,
                agreement=(shadow_id == selected_id)
                if shadow_id in options and selected_id
                else None,
                confidence=shadow_answer.confidence_calibrated,
                elapsed_ms=round((time.perf_counter() - shadow_started) * 1000, 3),
            )
        except Exception as exc:
            _logger.warning(
                "laya_shadow_comparison_failed",
                run_id=task.run_id,
                step=task.steps_taken + 1,
                error_type=type(exc).__name__,
            )

        return selected_action


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


def _visual_semantics_insufficient(
    task: TaskState,
    observation: AgentObservation,
) -> bool:
    text = " ".join(
        part for part in (task.user_goal, task.current_subgoal, task.task) if part
    ).casefold()
    words = set(re.findall(r"[a-z]+", text))
    cues = words & _VISUAL_CUES
    if re.search(
        r"\b(?:leftmost|rightmost|topmost|bottommost|upper (?:left|right)|"
        r"lower (?:left|right)|(?:left|right) side|on the (?:left|right))\b",
        text,
    ):
        cues.add("layout")
    if not cues:
        return False
    semantic_text = " ".join(
        part
        for element in observation.elements
        for part in (element.name or "", element.text or "", element.value or "")
    ).casefold()
    content_cues = cues & {"chart", "graph", "diagram", "image", "photo", "picture", "canvas"}
    if content_cues and words & _VISUAL_CONTENT_TASKS:
        return True
    if cues & {
        "color",
        "colour",
        "red",
        "blue",
        "green",
        "yellow",
        "orange",
        "purple",
        "icon",
        "layout",
    }:
        return not any(cue in semantic_text for cue in cues)
    return not any(cue in semantic_text for cue in cues)


def _vision_request(
    *,
    task: str,
    snapshot: SemanticSnapshot,
    observation: AgentObservation,
    screenshot: bytes,
) -> VisionRequest:
    if not snapshot.active_tab:
        raise ValueError("the visual request has no active browser tab")
    viewport_width = round(snapshot.viewport.width)
    viewport_height = round(snapshot.viewport.height)
    if viewport_width <= 0 or viewport_height <= 0:
        raise ValueError("the visual request has no valid viewport dimensions")

    visible_refs = {element.ref for element in observation.elements}
    targets: list[SemanticTargetMetadata] = []
    for element in snapshot.elements:
        if element.ref not in visible_refs or not element.visible or element.bbox is None:
            continue
        x = round(element.bbox.x)
        y = round(element.bbox.y)
        width = round(element.bbox.width)
        height = round(element.bbox.height)
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > viewport_width
            or y + height > viewport_height
        ):
            continue
        targets.append(
            SemanticTargetMetadata(
                ref=element.ref,
                role=element.role,
                name=(element.accessible_name or element.text or "")[:300] or None,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )
        if len(targets) >= 64:
            break

    return VisionRequest(
        task=task,
        observation=observation,
        screenshot=screenshot,
        mime_type="image/png",
        metadata=ScreenshotMetadata(
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            device_scale_factor=max(0.1, snapshot.viewport.device_scale_factor or 1.0),
            active_tab=snapshot.active_tab,
            state_generation=snapshot.state_generation,
        ),
        targets=targets,
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


def _action_signature(action: BrowserAction) -> dict[str, Any]:
    """Compare semantic targets without trusting model-supplied registry IDs."""
    signature = action.model_dump(mode="json", exclude_none=True)
    if action.target is not None:
        signature["target"] = {
            "ref": action.target.ref,
            "generation": action.target.generation,
        }
    return signature
