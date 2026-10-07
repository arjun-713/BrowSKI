"""LangGraph workflow nodes for observe, decide, execute, and verify."""

# LangGraph graph-builder internals have incomplete pyright stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
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
from browser_agent.agent.checkpoint_state import (
    action_audit_signature,
    action_audit_summary,
    bounded_action_timings,
    decision_checkpoint,
    decision_from_checkpoint,
    nonnegative_int,
    outcome_checkpoint,
    risk_checkpoint,
    same_checkpoint_page,
    snapshot_checkpoint,
    snapshot_from_checkpoint,
    stagnation_detector,
)
from browser_agent.agent.events import RuntimeEventType
from browser_agent.agent.safety import ActionRiskPolicy, RiskCategory
from browser_agent.agent.state import AgentState
from browser_agent.decisions.base import DecisionProvider
from browser_agent.progress.task_state import (
    ProgressTracker,
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


class RunControl(Protocol):
    pause_requested: bool
    stop_requested: bool
    stop_event: asyncio.Event


def build_agent_graph(
    agent: DecisionAgent,
    browser: BrowserSession,
    *,
    limits: GraphLimits,
    checkpointer: BaseCheckpointSaver[Any] | None,
    decision_provider: DecisionProvider | None = None,
    interrupt_before: Sequence[str] = (),
    control_for_run: Callable[[str], RunControl] | None = None,
    emit_event: Callable[[RuntimeEventType, str, int, str], Any] | None = None,
) -> Any:
    """Build the workflow around one live browser session.

    LangGraph checkpoints contain only values from ``AgentState``. The live
    session and decision agent are closure dependencies and never serialized.
    """

    # Full observations are needed for semantic decisions, but they are often
    # much larger than the bounded task state. Keep them in this runtime only;
    # SQLite checkpoints carry a compact summary and resume by re-observing.
    snapshot_cache: dict[str, tuple[SemanticSnapshot | None, SemanticSnapshot | None]] = {}
    decision_cache: dict[str, AgentDecision] = {}

    def cache_key(state: AgentState) -> str:
        task_state = state["task_state"]
        run_id = task_state.get("run_id")
        return str(run_id or "default")

    def cached_snapshot(state: AgentState, *, after: bool = False) -> SemanticSnapshot | None:
        pair = snapshot_cache.get(cache_key(state), (None, None))
        return pair[1 if after else 0]

    def save_snapshot(
        state: AgentState,
        snapshot: SemanticSnapshot,
        *,
        after: bool = False,
    ) -> None:
        key = cache_key(state)
        if key not in snapshot_cache and len(snapshot_cache) >= 4:
            snapshot_cache.pop(next(iter(snapshot_cache)))
        before, previous_after = snapshot_cache.get(key, (None, None))
        snapshot_cache[key] = (before, snapshot) if after else (snapshot, previous_after)

    def save_decision(state: AgentState, decision: AgentDecision) -> None:
        key = cache_key(state)
        if key not in decision_cache and len(decision_cache) >= 4:
            decision_cache.pop(next(iter(decision_cache)))
        decision_cache[key] = decision

    async def notify(
        state: AgentState,
        event_type: RuntimeEventType,
        status: str,
    ) -> None:
        if emit_event is None:
            return
        raw_task_state = state["task_state"]
        steps_taken = raw_task_state.get("steps_taken", 0)
        step = steps_taken if type(steps_taken) is int else 0
        if event_type in {
            RuntimeEventType.OBSERVATION_COMPLETED,
            RuntimeEventType.DECISION_MADE,
            RuntimeEventType.ACTION_STARTED,
        }:
            step += 1
        await emit_event(event_type, cache_key(state), step, status)

    def control_result(state: AgentState) -> dict[str, Any] | None:
        if control_for_run is None:
            return None
        control: RunControl = control_for_run(cache_key(state))
        if control.stop_requested:
            task_state = TaskState.model_validate(state["task_state"])
            task_state.status = "stopped"
            task_state.result_summary = "Stopped by the user at a safe action boundary."
            decision_cache.pop(cache_key(state), None)
            return {
                "task_state": task_state.model_dump(mode="json"),
                "status": "stopped",
                "result_summary": task_state.result_summary,
                "decision": None,
                "pending_confirmation": False,
                "confirmation_approved": False,
            }
        if control.pause_requested:
            interrupt({"kind": "user_pause"})
        return None

    async def current_snapshot(
        state: AgentState,
        *,
        after: bool = False,
    ) -> SemanticSnapshot:
        snapshot = cached_snapshot(state, after=after)
        if snapshot is None:
            snapshot = await browser.observe()
            save_snapshot(state, snapshot, after=after)
        return snapshot

    async def observe_node(state: AgentState) -> dict[str, Any]:
        controlled = control_result(state)
        if controlled is not None:
            return controlled
        snapshot = await browser.observe()
        save_snapshot(state, snapshot)
        await notify(state, RuntimeEventType.OBSERVATION_COMPLETED, "completed")
        return {"snapshot": snapshot_checkpoint(snapshot)}

    async def decide_node(state: AgentState) -> dict[str, Any]:
        controlled = control_result(state)
        if controlled is not None:
            return controlled
        decision_cache.pop(cache_key(state), None)
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

        if state["snapshot"] is None:
            return {"status": "failed", "result_summary": "Observation is missing."}

        # On process-restart resume, the live cache is empty. Re-observe the
        # current browser instead of rebuilding a full snapshot from checkpoint data.
        snapshot = await current_snapshot(state)

        task_state.llm_calls += 1
        control = control_for_run(cache_key(state)) if control_for_run is not None else None
        if control is None:
            decision = await agent.decide(
                snapshot,
                task_state.model_copy(deep=True),
                memory.model_copy(deep=True),
            )
        else:
            decision_task = asyncio.create_task(
                agent.decide(
                    snapshot,
                    task_state.model_copy(deep=True),
                    memory.model_copy(deep=True),
                )
            )
            stop_task = asyncio.create_task(control.stop_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {decision_task, stop_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if stop_task in done and control.stop_requested:
                    decision_task.cancel()
                    await asyncio.gather(decision_task, return_exceptions=True)
                    controlled = control_result(state)
                    if controlled is not None:
                        return controlled
                decision = await decision_task
            finally:
                if not stop_task.done():
                    stop_task.cancel()
                    await asyncio.gather(stop_task, return_exceptions=True)
        await notify(state, RuntimeEventType.DECISION_MADE, "completed")
        if decision.action is not None:
            save_decision(state, decision)
        if decision.ask_user:
            task_state.status = "awaiting_user"
            question_text = " ".join(decision.ask_user)[:2_000]
            task_state.result_summary = question_text
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision_checkpoint(decision),
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
                snapshot,
                verified_action=verified,
            )
            if task_state.done:
                task_state.status = "completed"
                task_state.result_summary = (
                    decision.result_summary or "Task completed with verified evidence."
                )
                return {
                    "task_state": task_state.model_dump(mode="json"),
                    "decision": decision_checkpoint(decision),
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
                "decision": decision_checkpoint(decision),
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
                "decision": decision_checkpoint(decision),
                "status": "failed",
                "result_summary": "Decision returned neither an action nor completion.",
                "pending_confirmation": False,
                "risk_assessment": None,
            }
        risk = ActionRiskPolicy().assess(decision.action, snapshot)
        needs_confirmation = limits.confirm_high_risk and risk.category == RiskCategory.HIGH
        return {
            "task_state": task_state.model_dump(mode="json"),
            "decision": decision_checkpoint(decision),
            "status": "running",
            "pending_confirmation": needs_confirmation,
            "confirmation_approved": False,
            "risk_assessment": risk_checkpoint(risk),
        }

    async def safety_node(state: AgentState) -> dict[str, Any]:
        controlled = control_result(state)
        if controlled is not None:
            return controlled
        if not state["pending_confirmation"]:
            return {"status": "running"}
        decision_data = state["decision"] or {}
        action = decision_data.get("action", {})
        risk = state["risk_assessment"] or {}
        await notify(state, RuntimeEventType.CONFIRMATION_REQUIRED, "running")
        approved = interrupt(
            {
                "kind": "high_risk_action_confirmation",
                "action": action_audit_summary(action),
                "risk": risk,
            }
        )
        if control_for_run is not None and control_for_run(cache_key(state)).stop_requested:
            task_state = TaskState.model_validate(state["task_state"])
            task_state.status = "stopped"
            task_state.result_summary = "Stopped by the user before the confirmed action."
            decision_cache.pop(cache_key(state), None)
            return {
                "task_state": task_state.model_dump(mode="json"),
                "pending_confirmation": False,
                "confirmation_approved": False,
                "status": "stopped",
                "result_summary": task_state.result_summary,
                "decision": None,
            }
        if approved is True:
            return {
                "pending_confirmation": False,
                "confirmation_approved": True,
                "status": "running",
                "result_summary": "High-risk action explicitly approved.",
            }
        decision_cache.pop(cache_key(state), None)
        return {
            "pending_confirmation": False,
            "confirmation_approved": False,
            "status": "failed",
            "result_summary": "High-risk action denied; no browser action was executed.",
        }

    async def execute_node(state: AgentState) -> dict[str, Any]:
        controlled = control_result(state)
        if controlled is not None:
            return controlled
        decision_data = state["decision"]
        if decision_data is None or state["snapshot"] is None:
            decision_cache.pop(cache_key(state), None)
            return {"status": "failed", "result_summary": "Action input is missing."}

        key = cache_key(state)
        decision = decision_cache.get(key)
        if cached_snapshot(state) is None:
            fresh_snapshot = await browser.observe()
            save_snapshot(state, fresh_snapshot)
            if not state["confirmation_approved"] or not same_checkpoint_page(
                state["snapshot"], fresh_snapshot
            ):
                decision_cache.pop(key, None)
                return {
                    "snapshot": snapshot_checkpoint(fresh_snapshot),
                    "decision": None,
                    "confirmation_approved": False,
                    "result_summary": (
                        "Browser session changed; refreshing the decision before acting."
                    ),
                }

            try:
                decision = decision_from_checkpoint(decision_data)
            except (TypeError, ValueError):
                decision = None
            if decision is None or decision.action is None:
                decision_cache.pop(key, None)
                return {
                    "snapshot": snapshot_checkpoint(fresh_snapshot),
                    "decision": None,
                    "confirmation_approved": False,
                    "result_summary": (
                        "Confirmed action could not be safely restored; deciding again."
                    ),
                }
            restored_risk = ActionRiskPolicy().assess(decision.action, fresh_snapshot)
            if restored_risk.category != RiskCategory.HIGH:
                decision_cache.pop(key, None)
                return {
                    "snapshot": snapshot_checkpoint(fresh_snapshot),
                    "decision": None,
                    "confirmation_approved": False,
                    "result_summary": "Confirmed action changed; deciding again.",
                }
            if decision.action.target is not None:
                target = fresh_snapshot.by_ref(decision.action.target.ref)
                if (
                    target is None
                    or not target.interactable
                    or not target.visible
                    or not target.enabled
                ):
                    decision_cache.pop(key, None)
                    return {
                        "snapshot": snapshot_checkpoint(fresh_snapshot),
                        "decision": None,
                        "confirmation_approved": False,
                        "result_summary": "Confirmed target changed; deciding again.",
                    }
                decision = decision.model_copy(
                    update={
                        "action": decision.action.model_copy(
                            update={
                                "target": target.model_copy(
                                    update={"generation": fresh_snapshot.state_generation}
                                )
                            }
                        )
                    }
                )
            save_decision(state, decision)
        else:
            decision = decision or AgentDecision.model_validate(decision_data)

        snapshot = await current_snapshot(state)
        if decision.action is None:
            decision_cache.pop(key, None)
            return {"status": "failed", "result_summary": "Decision has no action."}
        if snapshot.active_tab is None:
            decision_cache.pop(key, None)
            return {"status": "failed", "result_summary": "No active browser tab was observed."}

        controlled = control_result(state)
        if controlled is not None:
            return controlled

        try:
            await notify(state, RuntimeEventType.ACTION_STARTED, "running")
            outcome = await browser.act(decision.action, snapshot.active_tab)
        finally:
            decision_cache.pop(key, None)
        raw_execution = outcome.get("execution")
        execution_succeeded = isinstance(raw_execution, dict) and "Ok" in raw_execution
        await notify(
            state,
            RuntimeEventType.ACTION_COMPLETED,
            "completed" if execution_succeeded else "failed",
        )
        observed_after = await current_snapshot(state, after=True)
        raw_verification = outcome.get("verification", {})
        verification = (
            cast(dict[str, Any], raw_verification) if isinstance(raw_verification, dict) else {}
        )
        raw_delta = verification.get("state_delta")
        delta = SnapshotDelta.model_validate(raw_delta) if isinstance(raw_delta, dict) else None
        progress = ProgressTracker().compare(
            snapshot,
            observed_after,
            delta=delta,
            verification_status=str(verification.get("status", "UNKNOWN")),
        )
        return {
            "outcome": outcome_checkpoint(outcome),
            "after_snapshot": snapshot_checkpoint(observed_after),
            "last_progress": {
                "progressed": progress.progressed,
                "signals": [signal.value for signal in progress.signals],
            },
            "confirmation_approved": False,
        }

    async def verify_node(state: AgentState) -> dict[str, Any]:
        outcome = state["outcome"]
        if outcome is None:
            return {"status": "failed", "result_summary": "Executor returned no outcome."}

        execution = outcome.get("execution")
        verification = outcome.get("verification", {})
        mechanically_executed = isinstance(execution, dict) and "Ok" in execution
        verification_status = str(verification.get("status", "UNKNOWN"))
        verified = verification_status == "SUCCESS"
        await notify(
            state,
            RuntimeEventType.VERIFICATION_COMPLETED,
            "completed" if verified else "failed",
        )
        before_data = state["snapshot"]
        if before_data is None:
            return {"status": "failed", "result_summary": "Pre-action snapshot is missing."}
        before_snapshot = cached_snapshot(state) or snapshot_from_checkpoint(before_data)
        resumed_after_execution = cached_snapshot(state, after=True) is None
        after_snapshot_value = await current_snapshot(state, after=True)
        after_data = snapshot_checkpoint(after_snapshot_value)
        after_snapshot = after_snapshot_value
        expected_after = state["after_snapshot"]
        browser_state_changed = resumed_after_execution and (
            expected_after is None
            or expected_after["page_fingerprint"] != after_snapshot.page_fingerprint
        )
        if browser_state_changed:
            verification_status = "UNCERTAIN"
            verified = False
            progressed = False
            progress_signals: list[str] = []
        else:
            saved_progress = state["last_progress"]
            progress_matches_page = (
                expected_after is not None
                and expected_after["page_fingerprint"] == after_snapshot.page_fingerprint
            )
            if (
                progress_matches_page
                and isinstance(saved_progress, dict)
                and isinstance(saved_progress.get("progressed"), bool)
            ):
                signals = saved_progress.get("signals", [])
                progressed = saved_progress["progressed"]
                progress_signals = (
                    [value for value in cast(list[Any], signals) if isinstance(value, str)]
                    if isinstance(signals, list)
                    else []
                )
            else:
                measured = ProgressTracker().compare(
                    before_snapshot,
                    after_snapshot,
                    verification_status=verification_status,
                )
                progressed = measured.progressed
                progress_signals = [signal.value for signal in measured.signals]
        decision_data = state["decision"]
        action_data = decision_data.get("action") if decision_data is not None else None
        action_signature = action_audit_signature(action_data)
        event_task = TaskState.model_validate(state["task_state"])
        live_before_snapshot = cached_snapshot(state)
        snapshot_bytes = (
            len(live_before_snapshot.model_dump_json().encode("utf-8"))
            if live_before_snapshot is not None
            else None
        )
        observation_size = {
            "before_elements": before_data["element_count"],
            "after_elements": after_data["element_count"],
        }
        event: dict[str, Any] = {
            "run_id": event_task.run_id,
            "step_number": event_task.steps_taken + 1,
            "action": action_audit_summary(action_data),
            "action_signature": action_signature,
            "elapsed_ms": nonnegative_int(outcome.get("elapsed_ms")),
            "timings": bounded_action_timings(outcome.get("timings")),
            "semantic_snapshot_bytes": snapshot_bytes,
            "before_generation": nonnegative_int(outcome.get("before_generation")),
            "after_generation": nonnegative_int(outcome.get("after_generation")),
            "observation_size": observation_size,
            "risk_assessment": state["risk_assessment"],
            "verification": {"status": verification_status},
            "verification_status": verification_status,
            "before_fingerprint": before_snapshot.page_fingerprint,
            "after_fingerprint": after_snapshot.page_fingerprint,
            "progressed": progressed,
            "progress_signals": progress_signals,
            "reasoning_effort": (
                decision_data.get("reasoning_effort") if decision_data is not None else None
            ),
        }
        history_limit = max(0, limits.max_history_events)
        history_events = [*state["action_history"], event]
        history = history_events[-history_limit:] if history_limit else []

        if not mechanically_executed or not verified:
            details = verification_status.lower().replace("_", " ")
            if browser_state_changed:
                details = "browser state changed after process restart"
            elif not mechanically_executed:
                details = "browser action failed"
            task_state = TaskState.model_validate(state["task_state"])
            task_state.steps_taken += 1
            task_state.recovery_count += 1
            task_state.recovery_streak += 1
            memory = WorkingMemory.model_validate(state["memory"])
            failed_strategy = f"{action_signature}: {verification_status}"
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
            await notify(state, RuntimeEventType.RECOVERY_STARTED, "running")
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
            detector = stagnation_detector(history)
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
        task_state.stagnant_steps = 0 if progressed else task_state.stagnant_steps + 1
        if progressed:
            task_state.recovery_streak = 0
            task_state.replan_count = 0
        task_state.progress_signals = progress_signals
        memory = WorkingMemory.model_validate(state["memory"])
        action_type = "action"
        if isinstance(action_data, dict):
            action_type_value = cast(dict[str, Any], action_data).get("type")
            if isinstance(action_type_value, str):
                action_type = action_type_value
        memory.record_event(
            f"step {task_state.steps_taken}: {action_type}; "
            f"{'progress' if progressed else 'activity only'}"
        )
        memory.user_goal = task_state.user_goal or task_state.task
        memory.constraints = list(task_state.constraints)
        memory.current_subgoal = task_state.current_subgoal
        memory.next_milestone = task_state.next_milestone
        memory.checkpoint_summary = (
            f"step={task_state.steps_taken}; progress={progressed}; "
            f"page={after_snapshot.page_fingerprint[:48]}"
        )
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
            "last_progress": {"progressed": progressed, "signals": progress_signals},
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

    def route_execution(state: AgentState) -> str:
        return "decide" if state["decision"] is None else "verify"

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
    builder.add_conditional_edges(
        "execute",
        route_execution,
        {"decide": "decide", "verify": "verify"},
    )
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
