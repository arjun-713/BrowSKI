"""Subprocess helper used to prove LangGraph SQLite state survives process exit."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # type: ignore[reportMissingImports]
from langgraph.graph import END, START, StateGraph  # type: ignore[reportMissingTypeStubs]

from browser_agent import BrowserAction, BrowserSession, ElementRef
from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime


class WorkerState(TypedDict):
    count: int


class ResumeFormAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        checkbox = next(element for element in snapshot.elements if element.role == "checkbox")
        if "checked" in checkbox.state:
            return AgentDecision(done=True, result_summary="Terms accepted.")
        return AgentDecision(
            action=BrowserAction(
                type="check",
                target=ElementRef(
                    id=checkbox.id,
                    ref=checkbox.ref,
                    generation=checkbox.generation,
                ),
                checked=True,
            )
        )


async def run_runtime(database: Path, phase: str, fixture: Path) -> None:
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())
        async with AgentRuntime.open_sqlite(
            ResumeFormAgent(),
            browser,
            database,
            interrupt_before=("decide",) if phase == "runtime-write" else (),
        ) as runtime:
            if phase == "runtime-write":
                result = await runtime.run("Accept the signup terms.", run_id="runtime-restart")
            else:
                result = await runtime.resume("runtime-restart")
        print(json.dumps({"run_id": result.run_id, "status": result.status, "done": result.done}))


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
    if sys.argv[2].startswith("runtime-"):
        fixture = Path(sys.argv[3])
        asyncio.run(run_runtime(Path(sys.argv[1]), sys.argv[2], fixture))
    else:
        asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
