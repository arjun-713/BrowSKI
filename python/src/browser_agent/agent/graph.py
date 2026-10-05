"""LangGraph workflow nodes for observe, decide, execute, and verify."""

# LangGraph graph-builder internals have incomplete pyright stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Protocol, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from browser_agent._types import (
    AgentDecision,
    FailureKind,
    SemanticSnapshot,
    SnapshotDelta,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.safety import ActionRiskPolicy, RiskCategory
from browser_agent.agent.state import AgentState
from browser_agent.decisions.base import DecisionProvider
from browser_agent.progress.task_state import (
    ProgressTracker,
    StagnationDetector,
    StagnationSample,
    check_completion,
)
from browser_agent.recovery.high_level import RecoveryBudget, RecoveryContext, RecoveryPolicy
from browser_agent.session import BrowserSession


class DecisionAgent(Protocol):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision: ...


class GraphLimits(Protocol):
    max_steps: int
    max_llm_calls: int
    max_history_events: int
    max_stagnant_steps: int
    max_recovery_actions: int
    max_replans: int
    confirm_high_risk: bool


def build_agent_graph(
    agent: DecisionAgent,
    browser: BrowserSession,
    *,
    limits: GraphLimits,
    checkpointer: BaseCheckpointSaver[Any] | None,
    decision_provider: DecisionProvider | None = None,
    interrupt_before: Sequence[str] = (),
) -> Any:
    """Build the workflow around one live browser session.

    LangGraph checkpoints contain only values from ``AgentState``. The live
    session and decision agent are closure dependencies and never serialized.
    """

    async def observe_node(state: AgentState) -> dict[str, Any]:
        snapshot = await browser.observe()
        return {"snapshot": snapshot.model_dump(mode="json")}

    async def decide_node(state: AgentState) -> dict[str, Any]:
        task_state = TaskState.model_validate(state["task_state"])
        memory = WorkingMemory.model_validate(state["memory"])

        if task_state.steps_taken >= limits.max_steps:
            return {
                "status": "failed",
                "result_summary": f"Step limit ({limits.max_steps}) reached.",
            }
        if task_state.llm_calls >= limits.max_llm_calls:
            return {
                "status": "failed",
                "result_summary": f"Decision limit ({limits.max_llm_calls}) reached.",
            }
        if task_state.stagnant_steps >= limits.max_stagnant_steps:
            return {
                "status": "failed",
                "result_summary": (
                    f"Stagnation budget ({limits.max_stagnant_steps}) exhausted without progress."
                ),
            }

        snapshot_data = state["snapshot"]
        if snapshot_data is None:
            return {"status": "failed", "result_summary": "Observation is missing."}

        task_state.llm_calls += 1
        decision = await agent.decide(
            SemanticSnapshot.model_validate(snapshot_data),
            task_state.model_copy(deep=True),
            memory.model_copy(deep=True),
        )
        if decision.ask_user:
            task_state.status = "awaiting_user"
            question_text = " ".join(decision.ask_user)[:2_000]
            task_state.result_summary = question_text
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json", exclude_none=True),
                "status": "awaiting_user",
                "result_summary": question_text,
                "pending_confirmation": False,
                "risk_assessment": None,
            }

        if decision.plan_initialized is not None:
            task_state.plan_initialized = decision.plan_initialized

        if decision.milestones:
            task_state.plan_initialized = True
            if decision.replace_plan or not task_state.milestones:
                task_state.milestones = decision.milestones[:10]
                task_state.required_milestones = list(task_state.milestones)
                task_state.completed = [] if decision.replace_plan else task_state.completed
            for milestone, evidence in decision.milestone_evidence.items():
                if milestone in task_state.milestones and evidence.strip():
                    task_state.milestone_evidence[milestone] = evidence[:500]
            task_state.current_subgoal = decision.current_subgoal or (
                task_state.milestones[0] if task_state.milestones else None
            )
            task_state.next_milestone = decision.next_milestone
            memory.completed_milestones = list(task_state.completed)
            memory.current_subgoal = task_state.current_subgoal
            memory.next_milestone = task_state.next_milestone

        snapshot = SemanticSnapshot.model_validate(snapshot_data)
        previous_outcome = state["outcome"]
        previous_verification = (
            cast(dict[str, Any], previous_outcome.get("verification", {}))
            if previous_outcome
            else {}
        )
        if previous_verification.get("status") == "SUCCESS":
            visible_text = _visible_text(snapshot).casefold()
            for milestone in task_state.required_milestones:
                evidence = task_state.milestone_evidence.get(milestone)
                if (
                    milestone not in task_state.completed
                    and evidence
                    and evidence.casefold() in visible_text
                ):
                    task_state.completed.append(milestone)
                    memory.complete_milestone(milestone)
            remaining_milestones = [
                milestone
                for milestone in task_state.required_milestones
                if milestone not in task_state.completed
            ]
            if task_state.current_subgoal in task_state.completed:
                task_state.current_subgoal = (
                    remaining_milestones[0] if remaining_milestones else None
                )
                task_state.next_milestone = (
                    remaining_milestones[1] if len(remaining_milestones) > 1 else None
                )
                memory.current_subgoal = task_state.current_subgoal
                memory.next_milestone = task_state.next_milestone

        if decision.done:
            outcome = state["outcome"]
            verification: dict[str, Any] = (
                cast(dict[str, Any], outcome.get("verification", {})) if outcome else {}
            )
            verified = verification.get("status") == "SUCCESS"
            task_state.done = check_completion(
                task_state,
                SemanticSnapshot.model_validate(snapshot_data),
                verified_action=verified,
            )
            if task_state.done:
                task_state.status = "completed"
                task_state.result_summary = (
                    decision.result_summary or "Task completed with verified evidence."
                )
                return {
                    "task_state": task_state.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json", exclude_none=True),
                    "status": "completed",
                    "result_summary": task_state.result_summary,
                    "pending_confirmation": False,
                    "risk_assessment": None,
                }
            task_state.status = "failed"
            task_state.result_summary = (
                "Completion claim rejected: no recent deterministic action and task evidence "
                "satisfy the completion criteria."
            )
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json", exclude_none=True),
                "status": "failed",
                "result_summary": task_state.result_summary,
                "pending_confirmation": False,
                "risk_assessment": None,
            }
        if decision.action is None:
            if decision.milestones:
                task_state.status = "running"
                return {
                    "task_state": task_state.model_dump(mode="json"),
                    "memory": memory.model_dump(mode="json"),
                    "decision": None,
                    "status": "running",
                    "pending_confirmation": False,
                    "risk_assessment": None,
                }
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json", exclude_none=True),
                "status": "failed",
                "result_summary": "Decision returned neither an action nor completion.",
                "pending_confirmation": False,
                "risk_assessment": None,
            }
        snapshot = SemanticSnapshot.model_validate(snapshot_data)
        risk = ActionRiskPolicy().assess(decision.action, snapshot)
        needs_confirmation = limits.confirm_high_risk and risk.category == RiskCategory.HIGH
        return {
            "task_state": task_state.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json", exclude_none=True),
            "status": "running",
            "pending_confirmation": needs_confirmation,
            "risk_assessment": risk.model_dump(mode="json"),
        }

    async def safety_node(state: AgentState) -> dict[str, Any]:
        if not state["pending_confirmation"]:
            return {"status": "running"}
        decision_data = state["decision"] or {}
        action = decision_data.get("action", {})
        risk = state["risk_assessment"] or {}
        approved = interrupt(
            {
                "kind": "high_risk_action_confirmation",
                "action": action_audit_summary(action),
                "risk": risk,
            }
        )
        if approved is True:
            return {
                "pending_confirmation": False,
                "status": "running",
                "result_summary": "High-risk action explicitly approved.",
            }
        return {
            "pending_confirmation": False,
            "status": "failed",
            "result_summary": "High-risk action denied; no browser action was executed.",
        }

    async def execute_node(state: AgentState) -> dict[str, Any]:
        decision_data = state["decision"]
        snapshot_data = state["snapshot"]
        if decision_data is None or snapshot_data is None:
            return {"status": "failed", "result_summary": "Action input is missing."}

        decision = AgentDecision.model_validate(decision_data)
        snapshot = SemanticSnapshot.model_validate(snapshot_data)
        if decision.action is None:
            return {"status": "failed", "result_summary": "Decision has no action."}
        if snapshot.active_tab is None:
            return {"status": "failed", "result_summary": "No active browser tab was observed."}

        outcome = await browser.act(decision.action, snapshot.active_tab)
        after_snapshot = await browser.observe()
        return {
            "outcome": outcome,
            "after_snapshot": after_snapshot.model_dump(mode="json"),
        }

    async def verify_node(state: AgentState) -> dict[str, Any]:
        outcome = state["outcome"]
        if outcome is None:
            return {"status": "failed", "result_summary": "Executor returned no outcome."}

        execution = outcome.get("execution")
        verification = outcome.get("verification", {})
        mechanically_executed = isinstance(execution, dict) and "Ok" in execution
        verified = verification.get("status") == "SUCCESS"
        before_data = state["snapshot"]
        after_data = state["after_snapshot"]
        if before_data is None:
            return {"status": "failed", "result_summary": "Pre-action snapshot is missing."}
        if after_data is None:
            after_snapshot = await browser.observe()
            after_data = after_snapshot.model_dump(mode="json")
        before_snapshot = SemanticSnapshot.model_validate(before_data)
        after_snapshot = SemanticSnapshot.model_validate(after_data)
        raw_delta = verification.get("state_delta")
        delta = SnapshotDelta.model_validate(raw_delta) if isinstance(raw_delta, dict) else None
        progress = ProgressTracker().compare(
            before_snapshot,
            after_snapshot,
            delta=delta,
            verification_status=str(verification.get("status", "UNKNOWN")),
        )
        decision_data = state["decision"]
        action_data = decision_data.get("action") if decision_data is not None else None
        action_signature = action_audit_signature(action_data)
        event: dict[str, Any] = {
            "action": action_audit_summary(action_data),
            "action_signature": action_signature,
            "risk_assessment": state["risk_assessment"],
            "verification": verification,
            "verification_status": str(verification.get("status", "UNKNOWN")),
            "before_fingerprint": before_snapshot.page_fingerprint,
            "after_fingerprint": after_snapshot.page_fingerprint,
            "progressed": progress.progressed,
            "progress_signals": [signal.value for signal in progress.signals],
            "after_generation": outcome.get("after_generation"),
            "reasoning_effort": (
                decision_data.get("reasoning_effort") if decision_data is not None else None
            ),
        }
        history_limit = max(0, limits.max_history_events)
        history_events = [*state["action_history"], event]
        history = history_events[-history_limit:] if history_limit else []

        if not mechanically_executed or not verified:
            details = str(verification.get("status", "unknown outcome"))
            if not mechanically_executed and isinstance(execution, dict):
                execution_payload = cast(dict[str, Any], execution)
                execution_error = execution_payload.get("Err")
                if isinstance(execution_error, dict):
                    error_payload = cast(dict[str, Any], execution_error)
                    error_details = error_payload.get("details")
                    if isinstance(error_details, str):
                        details = error_details
            task_state = TaskState.model_validate(state["task_state"])
            task_state.steps_taken += 1
            task_state.recovery_count += 1
            task_state.recovery_streak += 1
            memory = WorkingMemory.model_validate(state["memory"])
            failed_strategy = f"{action_signature}: {verification.get('status', 'UNKNOWN')}"
            if failed_strategy not in memory.failed_strategies:
                memory.record_failed_strategy(failed_strategy)

            budget_values = dict(state["recovery_budget"])
            budget_values.setdefault("max_normal_replans", limits.max_replans)
            budget = RecoveryBudget(**budget_values)
            failure_kind = (
                FailureKind.EXECUTION if not mechanically_executed else FailureKind.VERIFICATION
            )
            recovery_policy = RecoveryPolicy()
            recovery_context = RecoveryContext(
                failure_kind=failure_kind,
                alternate_action_available=True,
                system_one_available=decision_provider is not None,
                reasoning_available=_reasoning_available(agent),
            )
            recovery = recovery_policy.next_step(recovery_context, budget)
            complexity_result: Any | None = None
            if recovery.step.value == "complexity_gate":
                complexity_result = _complexity_result(agent, task_state, before_snapshot)
                recovery = recovery_policy.next_step(
                    RecoveryContext(
                        failure_kind=failure_kind,
                        alternate_action_available=True,
                        system_one_available=decision_provider is not None,
                        reasoning_available=_reasoning_available(agent),
                        very_complex=_is_very_complex(complexity_result),
                    ),
                    budget,
                )
            if recovery.step.value in {"luna_normal_replan", "luna_high_replan"}:
                task_state.replan_count += 1
            classification: str | None = None
            if recovery.step.value == "system_one_classification" and decision_provider:
                try:
                    answer = await decision_provider.classify_recovery(
                        {"failure_kind": failure_kind.value},
                        failure_kind.value,
                    )
                    classification = (
                        str(answer.value) if answer.accepted is not False else "provider_abstained"
                    )
                except Exception as exc:
                    classification = f"provider_error:{type(exc).__name__}"
            event["recovery_kind"] = recovery.step.value
            event["recovery_classification"] = classification
            if complexity_result is not None:
                event["complexity_level"] = str(complexity_result.level)
                event["complexity_reasons"] = [str(reason) for reason in complexity_result.reasons]
            detector = _stagnation_detector(history)
            task_state.stagnant_steps = detector.stagnant_steps
            recovery_events = [
                *state["recovery_history"],
                {
                    "step": recovery.step.value,
                    "decision": recovery.decision,
                    "reason": recovery.reason,
                    "attempt": recovery.attempt,
                    "classification": classification,
                    **(
                        {
                            "complexity_level": str(complexity_result.level),
                            "complexity_reasons": [
                                str(reason) for reason in complexity_result.reasons
                            ],
                        }
                        if complexity_result is not None
                        else {}
                    ),
                },
            ]
            recovery_history = (
                recovery_events[-limits.max_history_events :] if limits.max_history_events else []
            )
            task_state.recovery_history = recovery_history
            memory.record_event(f"recovery {recovery.step.value}: {recovery.reason}")
            memory.checkpoint_summary = (
                f"step={task_state.steps_taken}; progress=false; recovery={recovery.step.value}"
            )
            can_continue = (
                (
                    recovery.step.value in {"reobserve", "alternate_bounded_action"}
                    or recovery.step.value
                    in {"luna_normal_replan", "complexity_gate", "luna_high_replan"}
                    and _reasoning_available(agent)
                    or (
                        recovery.step.value == "system_one_classification"
                        and classification in {"retry", "reacquire", "replan"}
                    )
                )
                and task_state.recovery_count <= limits.max_recovery_actions
                and task_state.stagnant_steps < limits.max_stagnant_steps
            )
            task_state.status = "running" if can_continue else "awaiting_user"
            task_state.result_summary = (
                f"Action was not verified ({details}). "
                f"Recovery: {recovery.reason}"
                + (f"; System One classification: {classification}" if classification else "")
            )
            return {
                "task_state": task_state.model_dump(mode="json"),
                "memory": memory.model_dump(mode="json"),
                "action_history": history,
                "decision": None,
                "outcome": {
                    "execution": {"Ok": mechanically_executed},
                    "verification": {"status": verification.get("status", "UNKNOWN")},
                },
                "recovery_budget": asdict(budget),
                "recovery_history": recovery_history,
                "snapshot": after_data,
                "after_snapshot": after_data,
                "status": "running" if can_continue else "awaiting_user",
                "result_summary": task_state.result_summary,
            }

        task_state = TaskState.model_validate(state["task_state"])
        task_state.steps_taken += 1
        task_state.stagnant_steps = 0 if progress.progressed else task_state.stagnant_steps + 1
        if progress.progressed:
            task_state.recovery_streak = 0
            task_state.replan_count = 0
        task_state.progress_signals = [signal.value for signal in progress.signals]
        memory = WorkingMemory.model_validate(state["memory"])
        action_type = "action"
        if isinstance(action_data, dict):
            action_type_value = cast(dict[str, Any], action_data).get("type")
            if isinstance(action_type_value, str):
                action_type = action_type_value
        memory.record_event(
            f"step {task_state.steps_taken}: {action_type}; "
            f"{'progress' if progress.progressed else 'activity only'}"
        )
        memory.user_goal = task_state.user_goal or task_state.task
        memory.constraints = list(task_state.constraints)
        memory.current_subgoal = task_state.current_subgoal
        memory.next_milestone = task_state.next_milestone
        memory.checkpoint_summary = (
            f"step={task_state.steps_taken}; progress={progress.progressed}; "
            f"url={after_snapshot.url[:200]}"
        )[:2_000]
        milestone = decision_data.get("completed_milestone") if decision_data is not None else None
        if isinstance(milestone, str):
            expected_evidence = task_state.milestone_evidence.get(milestone)
            if (
                milestone in task_state.milestones
                and expected_evidence
                and expected_evidence.casefold() in _visible_text(after_snapshot).casefold()
            ):
                if milestone not in task_state.completed:
                    task_state.completed.append(milestone)
                    memory.complete_milestone(milestone)
                    remaining = [
                        value
                        for value in task_state.required_milestones
                        if value not in task_state.completed
                    ]
                    task_state.current_subgoal = remaining[0] if remaining else None
                    task_state.next_milestone = remaining[1] if len(remaining) > 1 else None
                    memory.current_subgoal = task_state.current_subgoal
                    memory.next_milestone = task_state.next_milestone

        return {
            "task_state": task_state.model_dump(mode="json"),
            "memory": memory.model_dump(mode="json"),
            "action_history": history,
            "decision": None,
            "outcome": {
                "execution": {"Ok": mechanically_executed},
                "verification": {"status": verification.get("status", "UNKNOWN")},
            },
            "snapshot": after_data,
            "after_snapshot": after_data,
            "recovery_budget": state["recovery_budget"],
            "recovery_history": state["recovery_history"],
            "last_progress": progress.model_dump(mode="json"),
            "status": "running",
        }

    def route_decision(state: AgentState) -> str:
        if state["status"] != "running":
            return END
        decision = state["decision"]
        if decision is None:
            return "decide"
        return "safety" if decision.get("action") else END

    def route_safety(state: AgentState) -> str:
        return "execute" if state["status"] == "running" else END

    def route_verification(state: AgentState) -> str:
        return "observe" if state["status"] == "running" else END

    # LangGraph currently ships partial typing for its graph builder API.
    graph_builder = cast(Any, StateGraph)
    builder = graph_builder(AgentState)
    builder.add_node("observe", observe_node)
    builder.add_node("decide", decide_node)
    builder.add_node("safety", safety_node)
    builder.add_node("execute", execute_node)
    builder.add_node("verify", verify_node)
    builder.add_edge(START, "observe")
    builder.add_edge("observe", "decide")
    builder.add_conditional_edges("decide", route_decision)
    builder.add_conditional_edges(
        "safety",
        route_safety,
        {"execute": "execute", END: END},
    )
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges("verify", route_verification)
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=list(interrupt_before),
    )


def _visible_text(snapshot: SemanticSnapshot) -> str:
    parts = [snapshot.url, snapshot.title or "", snapshot.text_excerpt or ""]
    parts.extend(block.text for block in snapshot.text_blocks)
    for element in snapshot.elements:
        parts.extend((element.accessible_name or "", element.text or ""))
    return "\n".join(parts)


def action_audit_summary(action: Any) -> dict[str, str]:
    """Keep checkpoint and confirmation summaries free of submitted values."""
    if not isinstance(action, dict):
        return {"type": "unknown"}
    action_data = cast(dict[str, Any], action)
    summary = {"type": str(action_data.get("type", "unknown"))}
    target = action_data.get("target")
    if isinstance(target, dict):
        target_data = cast(dict[str, Any], target)
        target_ref = target_data.get("ref")
        if isinstance(target_ref, str):
            summary["target_ref"] = target_ref
    return summary


def action_audit_signature(action: Any) -> str:
    summary = action_audit_summary(action)
    target = summary.get("target_ref")
    return f"{summary['type']}:{target}" if target else summary["type"]


def _stagnation_detector(history: list[dict[str, Any]]) -> StagnationDetector:
    detector = StagnationDetector()
    for event in history:
        detector.observe(
            StagnationSample(
                state_fingerprint=str(event.get("after_fingerprint", "")),
                action_signature=str(event.get("action_signature", "")),
                verification_status=str(event.get("verification_status", "UNKNOWN")),
                progressed=bool(event.get("progressed", False)),
                recovery_kind=event.get("recovery_kind"),
            )
        )
    return detector


def _reasoning_available(agent: DecisionAgent) -> bool:
    return getattr(agent, "reasoning_provider", None) is not None


def _complexity_result(
    agent: DecisionAgent,
    task_state: TaskState,
    snapshot: SemanticSnapshot,
) -> Any | None:
    evaluate = getattr(agent, "complexity_for_recovery", None)
    if not callable(evaluate):
        return None
    return evaluate(task_state, snapshot, normal_replan_failed=True)


def _is_very_complex(result: Any | None) -> bool:
    return result is not None and str(getattr(result, "level", "normal")) in {
        "very_complex",
        "ComplexityLevel.VERY_COMPLEX",
    }
