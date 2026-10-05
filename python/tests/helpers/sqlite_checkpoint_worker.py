"""Subprocess helper used to prove LangGraph SQLite state survives process exit."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, TypedDict, cast

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[reportMissingImports]
from langgraph.graph import END, START, StateGraph  # type: ignore[reportMissingTypeStubs]

from browser_agent import BrowserAction, BrowserSession, ElementRef
from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime


class WorkerState(TypedDict):
    count: int


class PrivacyCheckpointAgent(Agent):
    def __init__(self, fixture_url: str) -> None:
        self.fixture_url = fixture_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = memory
        if "Account created" in (snapshot.text_excerpt or ""):
            return AgentDecision(done=True, result_summary="Account creation verified.")

        email = next(element for element in snapshot.elements if element.accessible_name == "Email")
        if email.value != CHECKPOINT_SECRET:
            return AgentDecision(
                reasoning=CHECKPOINT_REASONING_SECRET,
                result_summary=CHECKPOINT_RESULT_SECRET,
                action=BrowserAction(
                    type="type",
                    target=ElementRef(
                        ref=email.ref,
                        id=email.id,
                        generation=email.generation,
                    ),
                    text=CHECKPOINT_SECRET,
                ),
            )

        button = next(
            element for element in snapshot.elements if element.accessible_name == "Continue"
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(
                    ref=button.ref,
                    id=button.id,
                    generation=button.generation,
                ),
            )
        )


CHECKPOINT_SECRET = "checkpoint-private-marker-unique@example.invalid"
CHECKPOINT_URL_SECRET = "checkpoint-url-marker-unique"
CHECKPOINT_REASONING_SECRET = "checkpoint-reasoning-marker-unique"
CHECKPOINT_RESULT_SECRET = "checkpoint-result-marker-unique"


class ResumeProgressAgent(Agent):
    def __init__(self, *, stop_after_two_steps: bool = False) -> None:
        self.stop_after_two_steps = stop_after_two_steps

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = memory
        if self.stop_after_two_steps and task.steps_taken >= 2:
            # Simulate abrupt process loss after verified steps; skip cleanup intentionally.
            os._exit(73)
        if task.steps_taken >= 4:
            return AgentDecision(done=True, result_summary="Four verified clicks completed.")

        button = next(
            element for element in snapshot.elements if element.accessible_name == "Increment"
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(
                    id=button.id,
                    ref=button.ref,
                    generation=button.generation,
                ),
            )
        )


async def run_privacy_runtime(database: Path, phase: str, fixture: Path) -> None:
    fixture_url = f"{fixture.as_uri()}?token={CHECKPOINT_URL_SECRET}"
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture_url)
        async with AgentRuntime.open_sqlite(
            PrivacyCheckpointAgent(fixture_url),
            browser,
            database,
            config=AgentConfig(confirm_high_risk=False),
            interrupt_before=("verify",) if phase == "privacy-write" else (),
        ) as runtime:
            if phase == "privacy-write":
                await runtime.run(
                    "Enter an email and submit the signup form.",
                    run_id="privacy-restart",
                )
                os._exit(74)

            thread_config = {"configurable": {"thread_id": "privacy-restart"}}
            checkpoint = await runtime.graph.aget_state(thread_config)
            values = checkpoint.values
            raw_outcome = values.get("outcome")
            outcome = cast(dict[str, Any], raw_outcome) if isinstance(raw_outcome, dict) else {}
            raw_execution = outcome.get("execution")
            execution = (
                cast(dict[str, Any], raw_execution) if isinstance(raw_execution, dict) else {}
            )
            if "Ok" not in execution:
                raise AssertionError("expected a completed action before verify")
            if values["snapshot"]["url"] != "":
                raise AssertionError("checkpoint snapshot must not retain URL data")
            if "text" in values["decision"]["action"]:
                raise AssertionError("checkpoint decision must not retain typed text")
            if set(values["decision"]) != {"done", "action"}:
                raise AssertionError("checkpoint decision contains non-operational fields")

            result = await runtime.resume("privacy-restart")
            final_state = await runtime.graph.aget_state(thread_config)
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "done": result.done,
                    "steps_taken": result.steps_taken,
                    "history_events": len(final_state.values["action_history"]),
                }
            )
        )


async def run_runtime(database: Path, phase: str, fixture: Path) -> None:
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())
        async with AgentRuntime.open_sqlite(
            ResumeProgressAgent(stop_after_two_steps=phase == "runtime-write"),
            browser,
            database,
        ) as runtime:
            if phase == "runtime-write":
                result = await runtime.run(
                    "Complete four counter actions.", run_id="runtime-restart"
                )
            else:
                result = await runtime.resume("runtime-restart")
            graph_state = await runtime.graph.aget_state(
                {"configurable": {"thread_id": "runtime-restart"}}
            )
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "done": result.done,
                    "steps_taken": result.steps_taken,
                    "history_events": len(graph_state.values["action_history"]),
                }
            )
        )


def build_graph(checkpointer: AsyncSqliteSaver, *, pause_before_advance: bool) -> Any:
    builder: Any = StateGraph(WorkerState)

    def advance(state: WorkerState) -> WorkerState:
        return {"count": state["count"] + 1}

    builder.add_node("advance", advance)
    builder.add_edge(START, "advance")
    builder.add_edge("advance", END)
    interrupts = ["advance"] if pause_before_advance else []
    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupts)


async def run(database: Path, phase: str) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(database)) as checkpointer:
        graph = build_graph(checkpointer, pause_before_advance=phase == "write")
        config = {"configurable": {"thread_id": "sqlite-process-restart"}}
        if phase == "write":
            await graph.ainvoke({"count": 41}, config)
            return

        result = await graph.ainvoke(None, config)
        print(json.dumps(result))


if __name__ == "__main__":
    phase = sys.argv[2]
    fixture = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    if phase.startswith("privacy-"):
        if fixture is None:
            raise SystemExit("privacy phases require an M3 form fixture path")
        asyncio.run(run_privacy_runtime(Path(sys.argv[1]), phase, fixture))
    elif phase.startswith("runtime-"):
        if fixture is None:
            raise SystemExit("runtime phases require a fixture path")
        asyncio.run(run_runtime(Path(sys.argv[1]), phase, fixture))
    else:
        asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
