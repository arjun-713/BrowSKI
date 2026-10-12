"""GPT-6 Luna decisions with non-executing System One shadow comparison."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import structlog

from browser_agent._types import (
    AgentDecision,
    AgentObservation,
    BrowserAction,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.action_batch import (
    PendingActionBatch,
    advance_action_batch,
    mark_batch_action_started,
    prepare_action_batch,
)
from browser_agent.agent.luna_candidates import (
    action_candidates,
    action_signature,
    agent_observation,
    candidate_options,
    resolve_target,
)
from browser_agent.agent.runtime import Agent
from browser_agent.agent.shadow import ShadowDecisionManager
from browser_agent.agent.task_inventory import TaskInventory
from browser_agent.browser_code.contracts import BrowserCodeProposal, BrowserCodeResult
from browser_agent.decisions import (
    ActionCandidate,
    CandidatePolicy,
    DecisionProvider,
)
from browser_agent.decisions.action_matching import actions_match
from browser_agent.decisions.task_sites import DEFAULT_SITE_ALIASES
from browser_agent.persistence.run_metrics import RunMetricKind
from browser_agent.progress.evidence import local_browser_checks, task_terminal_text
from browser_agent.progress.task_state import check_completion
from browser_agent.reasoning import (
    ComplexityGate,
    ComplexityLevel,
    ComplexityResult,
    ComplexitySignals,
    ReasoningContext,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
    ReasoningProvider,
    ReasoningProviderRequestError,
    ReasoningPurpose,
    configured_luna_model,
)
from browser_agent.session import BrowserSession
from browser_agent.telemetry.debug_log import record_debug
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
        browser_code_enabled: bool = False,
        default_effort: ReasoningEffort = ReasoningEffort.LOW,
        site_aliases: Mapping[str, str] | None = None,
    ) -> None:
        self.decision_provider = decision_provider
        self.reasoning_provider = reasoning_provider
        self.model = configured_luna_model() if model is None else model
        self.candidate_policy = candidate_policy or CandidatePolicy()
        self.complexity_gate = complexity_gate or ComplexityGate()
        self.vision_provider = vision_provider
        self.screenshot_capture = screenshot_capture
        self.browser_code_enabled = browser_code_enabled
        self.default_effort = default_effort
        self._pending_browser_code_result: BrowserCodeResult | None = None
        self._vision_cache: dict[str, VisionInterpretation] = {}
        self._shadow: ShadowDecisionManager | None = None
        self.site_aliases = dict(DEFAULT_SITE_ALIASES if site_aliases is None else site_aliases)
        self._task_inventory = TaskInventory()
        self.last_reasoning_calls = 0
        self._batch: PendingActionBatch | None = None

    def bind_browser(self, browser: BrowserSession) -> None:
        self._task_inventory.bind_browser(browser)

    async def refresh_task_evidence(self, snapshot: SemanticSnapshot, task: TaskState) -> None:
        await self._task_inventory.refresh(snapshot, task, self.site_aliases)

    async def finish_run(self) -> None:
        """Stop owned optional work at pause, termination, or cancellation."""
        if self._shadow is not None:
            await self._shadow.close()
            self._shadow = None
        if self._batch is not None:
            self._batch.clear()
            self._batch = None

    def accept_browser_code_result(self, result: BrowserCodeResult) -> None:
        """Stage one ephemeral transform result for exactly the next Luna call."""
        if not self.browser_code_enabled:
            raise ValueError("browser-code capability is disabled")
        self._pending_browser_code_result = result

    def clear_browser_code_result(self) -> None:
        """Discard pending transform output on pause, stop, or stale-generation paths."""
        self._pending_browser_code_result = None
        if self._batch is not None:
            self._batch.clear()
            self._batch = None

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        self.last_reasoning_calls = 0
        await self.refresh_task_evidence(snapshot, task)
        observation = agent_observation(snapshot)
        has_completion_criteria = bool(task.required_milestones or task_terminal_text(task))
        if (
            has_completion_criteria
            and all(self._task_inventory.destination_checks.values())
            and "verification_success" in task.progress_signals
            and check_completion(
                task,
                snapshot,
                verified_action=True,
            )
        ):
            return AgentDecision(
                done=True,
                result_summary="Task completion is supported by verified browser evidence.",
            )
        visual_context = await self._visual_context(snapshot, task, observation)
        if isinstance(visual_context, AgentDecision):
            return visual_context

        candidates = action_candidates(
            snapshot=snapshot,
            task=task,
            memory=memory,
            observation=observation,
            candidate_policy=self.candidate_policy,
            owned_tab_urls=list(self._task_inventory.owned_tab_urls.values()),
            site_aliases=self.site_aliases,
        )
        options = candidate_options(candidates)
        if self._batch is not None:
            queued = advance_action_batch(
                self._batch,
                snapshot,
                run_id=task.run_id or "standalone",
                page_id=snapshot.active_tab or "current",
                verification_success="verification_success" in task.progress_signals,
                recovery_in_progress=task.recovery_streak > 0,
                owned_tab_urls=self._task_inventory.owned_tab_urls,
            )
            if queued is not None:
                record_debug(
                    "decision.batch_step", {"type": queued.type, "target_ref": queued.target_ref}
                )
                return await self._bounded_luna_action(
                    ReasoningDecision(outcome=ReasoningOutcome.NEXT_ACTION, action=queued),
                    observation=observation,
                    snapshot=snapshot,
                    task=task,
                    candidates=candidates,
                    options=options,
                    reasoning="Executing the next locally revalidated Luna action.",
                    effort=self.default_effort,
                    purpose=ReasoningPurpose.CHOOSE_ACTION,
                )
            self._batch = None

        if not task.plan_initialized:
            return await self._ask_luna(
                observation,
                task,
                memory,
                snapshot=snapshot,
                purpose=ReasoningPurpose.PLAN,
                candidate_options=options,
                bounded_candidates=candidates,
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
                candidate_options=options,
                bounded_candidates=candidates,
                visual_context=visual_context,
            )
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
                self.record_run_metric(task.run_id, RunMetricKind.VISION_CALL)
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
        # The current plan is a flat ordered list with one active subgoal.
        # Remaining milestones are not concurrent or nested dependencies.
        active_subgoals = 1 if task.current_subgoal else 0
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
        if gate_result.level == ComplexityLevel.NORMAL:
            effort = self.default_effort
        if purpose == ReasoningPurpose.REPLAN and task.recovery_history:
            latest_recovery_step = task.recovery_history[-1].get("step")
            if latest_recovery_step == "luna_normal_replan":
                effort = self.default_effort
            elif latest_recovery_step == "luna_high_replan":
                effort = ReasoningEffort.HIGH
        browser_code_result = self._pending_browser_code_result
        self._pending_browser_code_result = None
        context = ReasoningContext(
            purpose=purpose,
            task=task,
            memory=memory,
            observation=observation,
            prior_summary=memory.checkpoint_summary or "",
            visual_observation=visual_context,
            failure_summary=failure_summary,
            candidate_options=candidate_options or {},
            browser_checks=local_browser_checks(task, snapshot, observation, self.candidate_policy)
            | self._task_inventory.destination_checks,
            task_tab_labels=self._task_inventory.task_tab_labels,
            browser_code_enabled=self.browser_code_enabled,
            browser_code_result=browser_code_result,
        )
        try:
            # Provider implementations can cross an untyped SDK/plugin boundary.
            self.record_run_metric(task.run_id, _luna_metric_kind(effort))
            self.last_reasoning_calls += 1
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
            message = (
                exc.user_message
                if isinstance(exc, ReasoningProviderRequestError)
                else "Luna reasoning was unavailable. Review the current browser state "
                "and provide guidance before continuing."
            )
            return AgentDecision(
                ask_user=[message],
                reasoning_effort=effort.value,
            )

        reasoning = result.summary[:2_000]
        if result.outcome == ReasoningOutcome.BROWSER_CODE:
            proposal: BrowserCodeProposal | None = result.browser_code
            if (
                not self.browser_code_enabled
                or purpose != ReasoningPurpose.CHOOSE_ACTION
                or proposal is None
            ):
                return AgentDecision(
                    ask_user=["Browser-code transforms are unavailable for this decision."],
                    reasoning_effort=effort.value,
                )
            return AgentDecision(
                browser_code=proposal,
                reasoning=reasoning,
                reasoning_effort=effort.value,
            )
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
                current_subgoal=(
                    result.current_subgoal
                    if result.current_subgoal in result.milestones
                    else result.milestones[0]
                ),
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

        if result.outcome == ReasoningOutcome.NEXT_ACTION and result.candidate_actions:
            authorized: list[BrowserAction] = []
            for candidate in bounded_candidates or []:
                try:
                    bound = candidate.to_browser_action(resolve_target(candidate, snapshot))
                except ValueError:
                    continue
                if bound is not None:
                    authorized.append(bound)
            batch = prepare_action_batch(
                result.candidate_actions,
                authorized,
                snapshot,
                run_id=task.run_id or "standalone",
                page_id=snapshot.active_tab or "current",
            )
            if batch is None:
                return AgentDecision(
                    ask_user=["Luna proposed an unsupported or unauthorized action batch."],
                    reasoning_effort=effort.value,
                )
            first = batch.actions[0]
            mark_batch_action_started(batch, first)
            self._batch = batch
            record_debug("decision.batch_authorized", {"count": len(batch.actions)})
            result = result.model_copy(update={"action": first, "candidate_actions": []})

        return await self._bounded_luna_action(
            result,
            observation=observation,
            snapshot=snapshot,
            task=task,
            candidates=bounded_candidates or [],
            options=candidate_options or {},
            reasoning=reasoning,
            effort=effort,
            purpose=purpose,
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
        purpose: ReasoningPurpose,
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
        comparisons: list[dict[str, object]] = []
        if proposed is not None:
            proposed_signature = action_signature(proposed)
            for index, candidate in enumerate(candidates):
                candidate_id = f"c{index + 1:02d}"
                try:
                    candidate_action = candidate.to_browser_action(
                        resolve_target(candidate, snapshot)
                    )
                except ValueError:
                    comparisons.append(
                        {"candidate_id": candidate_id, "status": "target_resolution_failed"}
                    )
                    continue
                if candidate_action is None:
                    comparisons.append({"candidate_id": candidate_id, "status": "not_executable"})
                    continue
                signature = action_signature(candidate_action)
                comparisons.append(
                    {
                        "candidate_id": candidate_id,
                        "action": signature,
                        "differing_fields": sorted(
                            field
                            for field in signature.keys() | proposed_signature.keys()
                            if signature.get(field) != proposed_signature.get(field)
                        ),
                    }
                )
                if actions_match(proposed, candidate_action):
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
        validation_reason = "action_binding_failed"
        if proposed is not None:
            validation_reason = "signature_mismatch"
        if action is not None:
            validation_reason = "matched"
        record_debug(
            "decision.candidate_validation",
            {
                "accepted": action is not None,
                "reason": validation_reason,
                "proposed_action": result.action.model_dump(mode="json", exclude_none=True),
                "bounded_candidates": options,
                "comparisons": comparisons,
                "selected_candidate": luna_id,
            },
            step=task.steps_taken + 1,
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
                evidence_ref=(
                    result.evidence_ref if purpose == ReasoningPurpose.CHOOSE_ACTION else None
                ),
                plan_initialized=True,
                current_subgoal=task.current_subgoal,
                reasoning=reasoning or "Selected by GPT-6 Luna from bounded semantic actions.",
                reasoning_effort=effort.value,
            )

        if self._shadow is None:
            self._shadow = ShadowDecisionManager(self.decision_provider)
        shadow_options = {key: value.rsplit("; action: ", 1)[-1] for key, value in options.items()}
        scheduled = self._shadow.schedule_choice(
            {
                "task": task.user_goal or task.task,
                "current_subgoal": task.current_subgoal or task.task,
                "recent_outcome": ", ".join(task.progress_signals),
            },
            shadow_options,
            luna_id or "",
            run_id=task.run_id,
            step=task.steps_taken + 1,
        )
        if scheduled:
            self.record_run_metric(task.run_id, RunMetricKind.LAYA_SHADOW_DECISION)
            # Yield once to start owned optional I/O; never await its inference.
            await asyncio.sleep(0)
        return AgentDecision(
            action=action,
            evidence_ref=(
                result.evidence_ref if purpose == ReasoningPurpose.CHOOSE_ACTION else None
            ),
            plan_initialized=True,
            current_subgoal=task.current_subgoal,
            reasoning=reasoning or "Selected by GPT-6 Luna from bounded semantic actions.",
            reasoning_effort=effort.value,
        )


def _luna_metric_kind(effort: ReasoningEffort) -> RunMetricKind:
    return {
        ReasoningEffort.NONE: RunMetricKind.LUNA_NONE_EFFORT_CALL,
        ReasoningEffort.LOW: RunMetricKind.LUNA_LOW_EFFORT_CALL,
        ReasoningEffort.HIGH: RunMetricKind.LUNA_HIGH_EFFORT_CALL,
    }[effort]


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
