"""Pre-dispatch invalidation when browser state changes during a decision."""

from pathlib import Path

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentRuntime
from browser_agent.agent.interference import same_decision_state


class InterferingAgent(Agent):
    def __init__(self, browser: BrowserSession) -> None:
        self.browser = browser
        self.calls = 0

    async def decide(
        self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
    ) -> AgentDecision:
        del task, memory
        self.calls += 1
        if self.calls > 1:
            return AgentDecision(ask_user=["Review your changed form value before continuing."])
        field = next(element for element in snapshot.elements if element.role == "textbox")
        button = next(element for element in snapshot.elements if element.role == "button")
        # Simulate an independently verified user edit while the decision is
        # outstanding. The planned click still refers to the old observation.
        await self.browser.act(
            BrowserAction(
                type="type",
                target=ElementRef(id=field.id, ref=field.ref, generation=field.generation),
                text="Changed by user",
                clear=True,
            )
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(id=button.id, ref=button.ref, generation=button.generation),
            )
        )


@pytest.mark.asyncio
async def test_user_edit_invalidates_action_before_dispatch(tmp_path: Path) -> None:
    page = tmp_path / "interference.html"
    page.write_text(
        "<html><head><title>Unclicked</title></head><body>"
        "<label>Name<input value='Original'></label>"
        "<button type='button' onclick=\"document.title='Clicked';"
        "this.textContent='Clicked'\">Continue</button></body></html>"
    )
    async with BrowserSession() as browser:
        await browser.navigate(page.as_uri())
        before = await browser.observe()
        agent = InterferingAgent(browser)
        result = await AgentRuntime(agent, browser).run("Review the name and continue.")
        after = await browser.observe()
        assert result.status == "awaiting_user"
        assert agent.calls == 2
        assert result.steps_taken == 0
        assert after.title == "Unclicked"
        assert (
            next(element.value for element in after.elements if element.role == "textbox")
            == "Changed by user"
        )
        assert before.state_generation == after.state_generation
        assert not same_decision_state(before, after)


@pytest.mark.asyncio
async def test_unchanged_observation_remains_eligible(tmp_path: Path) -> None:
    page = tmp_path / "stable.html"
    page.write_text("<button type='button'>Stable button</button>")
    async with BrowserSession() as browser:
        await browser.navigate(page.as_uri())
        before = await browser.observe()
        after = await browser.observe()
        assert same_decision_state(before, after)
