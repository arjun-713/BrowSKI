"""LangGraph workflow nodes for observe, decide, execute, and verify."""

# LangGraph graph-builder internals have incomplete pyright stubs.
# pyright: reportMissingTypeStubs=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from browser_agent._types import (
    AgentDecision,
    SemanticSnapshot,
    TaskState,
    WorkingMemory,
)
from browser_agent.agent.state import AgentState
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


def build_agent_graph(
    agent: DecisionAgent,
    browser: BrowserSession,
    *,
    limits: GraphLimits,
    checkpointer: BaseCheckpointSaver[Any] | None,
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

        snapshot_data = state["snapshot"]
        if snapshot_data is None:
            return {"status": "failed", "result_summary": "Observation is missing."}

        task_state.llm_calls += 1
        decision = await agent.decide(
            SemanticSnapshot.model_validate(snapshot_data),
            task_state,
            memory,
        )
        if decision.done:
            task_state.done = True
            summary = decision.result_summary or "Task completed."
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json", exclude_none=True),
                "status": "completed",
                "result_summary": summary,
            }
        if decision.action is None:
            return {
                "task_state": task_state.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json", exclude_none=True),
                "status": "failed",
                "result_summary": "Decision returned neither an action nor completion.",
            }
        return {
            "task_state": task_state.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json", exclude_none=True),
            "status": "running",
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
        return {"outcome": outcome}

    async def verify_node(state: AgentState) -> dict[str, Any]:
        outcome = state["outcome"]
        if outcome is None:
            return {"status": "failed", "result_summary": "Executor returned no outcome."}

        execution = outcome.get("execution")
        verification = outcome.get("verification", {})
        mechanically_executed = isinstance(execution, dict) and "Ok" in execution
        verified = verification.get("status") == "SUCCESS"
        if not mechanically_executed or not verified:
            detail_value = verification.get("observed") or verification.get("expected")
            details = detail_value if isinstance(detail_value, str) else None
            if not mechanically_executed and isinstance(execution, dict):
                execution_payload = cast(dict[str, Any], execution)
                execution_error = execution_payload.get("Err")
                if isinstance(execution_error, dict):
                    error_payload = cast(dict[str, Any], execution_error)
                    error_details = error_payload.get("details")
                    if isinstance(error_details, str):
                        details = error_details
            return {
                "status": "failed",
                "result_summary": f"Action was not verified: {details or 'unknown outcome'}",
            }

        task_state = TaskState.model_validate(state["task_state"])
        task_state.steps_taken += 1
        memory = WorkingMemory.model_validate(state["memory"])
        decision_data = state["decision"]
        action_data = decision_data.get("action") if decision_data is not None else None
        action_type = "action"
        if isinstance(action_data, dict):
            action_type_value = cast(dict[str, Any], action_data).get("type")
            if isinstance(action_type_value, str):
                action_type = action_type_value
        memory.record_event(f"step {task_state.steps_taken}: {action_type} verified")

        event: dict[str, Any] = {
            "action": action_data,
            "verification": verification,
            "after_generation": outcome.get("after_generation"),
        }
        history_limit = max(0, limits.max_history_events)
        history_events = [*state["action_history"], event]
        history = history_events[-history_limit:] if history_limit else []
        return {
            "task_state": task_state.model_dump(mode="json"),
            "memory": memory.model_dump(mode="json"),
            "action_history": history,
            "status": "running",
        }

    def route_decision(state: AgentState) -> str:
        if state["status"] != "running":
            return END
        decision = state["decision"]
        return "execute" if decision is not None and decision.get("action") else END

    def route_verification(state: AgentState) -> str:
        return "observe" if state["status"] == "running" else END

    # LangGraph currently ships partial typing for its graph builder API.
    graph_builder = cast(Any, StateGraph)
    builder = graph_builder(AgentState)
    builder.add_node("observe", observe_node)
    builder.add_node("decide", decide_node)
    builder.add_node("execute", execute_node)
    builder.add_node("verify", verify_node)
    builder.add_edge(START, "observe")
    builder.add_edge("observe", "decide")
    builder.add_conditional_edges("decide", route_decision)
    builder.add_edge("execute", "verify")
    builder.add_conditional_edges("verify", route_verification)
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=list(interrupt_before),
    )
