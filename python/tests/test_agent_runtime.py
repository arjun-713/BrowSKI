"""M4 graph tests use only local fixtures and a deterministic fake agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/m3/form-flow.html"


class FormAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=FIXTURE.as_uri()))

        checkbox = next(element for element in snapshot.elements if element.role == "checkbox")
        if "checked" in checkbox.state:
            return AgentDecision(done=True, result_summary="Terms accepted.")

        target = ElementRef(
            id=checkbox.id,
            ref=checkbox.ref,
            generation=checkbox.generation,
        )
        return AgentDecision(action=BrowserAction(type="check", target=target, checked=True))


class CompleteAfterObserveAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        return AgentDecision(done=True, result_summary="No action required.")


async def test_graph_executes_verified_actions_on_local_fixture() -> None:
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(FormAgent(), browser)
        result = await runtime.run("Open the signup fixture and accept terms.")

        assert result.done
        assert result.steps_taken == 2
        assert result.llm_calls == 3
        snapshot = await browser.observe()
        checkbox = next(el for el in snapshot.elements if el.role == "checkbox")
        assert "checked" in checkbox.state


async def test_graph_checkpoint_resumes_with_same_thread_state(tmp_path: Path) -> None:
    async with BrowserSession.launch() as browser:
        database = tmp_path / "agent-checkpoints.sqlite"
        async with AgentRuntime.open_sqlite(
            CompleteAfterObserveAgent(),
            browser,
            database,
            interrupt_before=("decide",),
        ) as first:
            pending = await first.run("Finish after observing.", run_id="resume-test")
            assert not pending.done
            state = await first.graph.aget_state({"configurable": {"thread_id": "resume-test"}})
            assert state.next

        async with AgentRuntime.open_sqlite(
            CompleteAfterObserveAgent(), browser, database
        ) as resumed_runtime:
            completed = await resumed_runtime.resume("resume-test")

        assert completed.done
        assert completed.task == "Finish after observing."
