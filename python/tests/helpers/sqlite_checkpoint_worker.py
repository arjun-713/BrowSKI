"""Subprocess helper used to prove LangGraph SQLite state survives process exit."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph


class WorkerState(TypedDict):
    count: int


def build_graph(checkpointer: AsyncSqliteSaver, *, pause_before_advance: bool) -> Any:
    builder = StateGraph(WorkerState)

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
    asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
