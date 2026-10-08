"""Actual isolated transforms through the graph, with no model requests."""

from pathlib import Path

import pytest

from browser_agent import AgentDecision, BrowserSession
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime
from browser_agent.agent.events import RuntimeEvent, RuntimeEventType
from browser_agent.browser_code import BrowserCodeProposal, BrowserCodeResult


class LocalTransformAgent(Agent):
    def __init__(self) -> None:
        self.result: BrowserCodeResult | None = None

    def accept_browser_code_result(self, result: BrowserCodeResult) -> None:
        self.result = result

    async def decide(
        self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
    ) -> AgentDecision:
        del snapshot, task, memory
        if self.result is not None:
            return AgentDecision(ask_user=["Review the extracted local data before continuing."])
        return AgentDecision(
            browser_code=BrowserCodeProposal(
                script="data => ({summary: 'ephemeral-output-marker-731', records: []})",
                purpose="Summarize collected semantic data",
                reason="The standard browser actions do not express semantic data transformation.",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_graph_transform_is_gated_ephemeral_and_traced(tmp_path: Path, enabled: bool) -> None:
    page = tmp_path / "local-data.html"
    page.write_text("<html><head><title>Local data</title></head><body>Fixture data</body></html>")
    database = tmp_path / "checkpoints.sqlite"
    events: list[RuntimeEvent] = []

    async def record(event: RuntimeEvent) -> None:
        events.append(event)

    agent = LocalTransformAgent()
    async with BrowserSession(browser_code_enabled=enabled) as browser:
        await browser.navigate(page.as_uri())
        async with AgentRuntime.open_sqlite(
            agent, browser, database=database, event_sink=record
        ) as runtime:
            result = await runtime.run("Summarize local fixture data.")
            state = await runtime.graph.aget_state({"configurable": {"thread_id": result.run_id}})
            assert "ephemeral-output-marker-731" not in str(state.values)
            assert "data =>" not in str(state.values)
        assert result.status == ("awaiting_user" if enabled else "failed")
        assert agent.result is not None if enabled else agent.result is None
        if enabled:
            assert result.steps_taken == 1
            assert RuntimeEventType.BROWSER_CODE_COMPLETED in [event.type for event in events]
        assert "ephemeral-output-marker-731" not in str(events)
        assert "data =>" not in str(events)
        assert (await browser.observe()).title == "Local data"
    assert b"ephemeral-output-marker-731" not in database.read_bytes()
