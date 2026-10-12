"""One active task owns a runtime's browser and agent state at a time."""

from __future__ import annotations

import asyncio

import pytest

from browser_agent._types import AgentDecision, SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime
from browser_agent.session import BrowserSession

pytestmark = pytest.mark.asyncio


class BlockingAgent(Agent):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        del snapshot, task, memory
        self.started.set()
        await self.release.wait()
        return AgentDecision(ask_user=["Pause after this test decision."])


async def test_distinct_run_ids_cannot_overlap_and_next_run_is_accepted() -> None:
    async with BrowserSession.launch() as browser:
        agent = BlockingAgent()
        runtime = AgentRuntime(agent, browser)
        first_run = asyncio.create_task(runtime.run("First task", run_id="first-run"))
        try:
            await asyncio.wait_for(agent.started.wait(), timeout=10)

            with pytest.raises(ValueError, match="another browser task"):
                await runtime.run("Second task", run_id="second-run")
            with pytest.raises(ValueError, match="another browser task"):
                await runtime.resume("second-run")
            with pytest.raises(ValueError, match="another browser task"):
                await runtime.resume_with_confirmation("second-run", approved=True)
        finally:
            agent.release.set()

        first_result = await first_run
        assert first_result.status == "awaiting_user"

        second_result = await runtime.run("Second task", run_id="second-run")
        assert second_result.status == "awaiting_user"
