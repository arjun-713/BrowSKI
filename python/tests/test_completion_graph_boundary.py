"""Real browser completion proposals preserve proof and bounded continuation."""

from pathlib import Path

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime


class _CompletionAgent(Agent):
    def __init__(self, *, repair: bool) -> None:
        self.calls = 0
        self.repair = repair

    async def decide(
        self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
    ) -> AgentDecision:
        _ = task, memory
        self.calls += 1
        milestone = "Save the requested effect"
        evidence = {milestone: "visible_text:Requested effect saved"}
        if self.calls > 1 and (not self.repair or self.calls == 2):
            return AgentDecision(
                done=True,
                milestones=[milestone],
                milestone_evidence={milestone: "visible_text:Unrelated change"},
            )
        name = "Start" if self.calls == 1 else "Finish"
        target = next(item for item in snapshot.elements if item.accessible_name == name)
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(ref=target.ref, id=target.id, generation=target.generation),
            ),
            milestones=[milestone],
            milestone_evidence=evidence,
            plan_initialized=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [False, True])
async def test_completion_proposal_cannot_replace_unfinished_proof(
    tmp_path: Path, repair: bool
) -> None:
    fixture = tmp_path / "completion.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
  <body>
    <p role="status">Waiting</p>
    <button onclick="document.querySelector('p').textContent = 'Unrelated change'">
      Start
    </button>
    <button onclick="document.querySelector('p').textContent = 'Requested effect saved'">
      Finish
    </button>
  </body>
</html>
""",
        encoding="utf-8",
    )
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())
        agent = _CompletionAgent(repair=repair)
        runtime = AgentRuntime(
            agent, browser, config=AgentConfig(max_llm_calls=4, max_stagnant_steps=3)
        )
        result = await runtime.run("Save the requested effect.")

        assert result.done is repair
        assert result.milestone_evidence == {
            "Save the requested effect": "visible_text:Requested effect saved"
        }
        assert agent.calls <= 4
        if repair:
            assert result.status == "completed"
            assert agent.calls == 3
        else:
            assert result.status == "failed"
            assert "Save the requested effect" not in result.completed


class _ReplanningAgent(Agent):
    def __init__(self) -> None:
        self.calls = 0
        self.evidence: dict[str, str] = {}

    async def decide(
        self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
    ) -> AgentDecision:
        _ = task, memory
        self.calls += 1
        start = next(item for item in snapshot.elements if item.accessible_name == "Start")
        milestones = ["Start workflow", "Finish workflow"]
        if self.calls == 1:
            self.evidence = {
                milestones[0]: f"verified_action:click:{start.ref}",
                milestones[1]: "visible_text:Unknown future status",
            }
        if self.calls == 2:
            self.evidence[milestones[1]] = "visible_text:Workflow finished"
            return AgentDecision(
                milestones=milestones,
                milestone_evidence=dict(self.evidence),
                replace_plan=True,
                plan_initialized=True,
            )
        name = "Start" if self.calls == 1 else "Finish"
        target = next(item for item in snapshot.elements if item.accessible_name == name)
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(ref=target.ref, id=target.id, generation=target.generation),
            ),
            milestones=milestones if self.calls == 1 else [],
            milestone_evidence=dict(self.evidence) if self.calls == 1 else {},
            plan_initialized=True,
        )


@pytest.mark.asyncio
async def test_replanning_preserves_completed_steps_with_unchanged_proof(tmp_path: Path) -> None:
    fixture = tmp_path / "replan.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en">
  <body>
    <p role="status">Waiting</p>
    <button onclick="document.querySelector('p').textContent = 'Workflow started'">
      Start
    </button>
    <button onclick="document.querySelector('p').textContent = 'Workflow finished'">
      Finish
    </button>
  </body>
</html>
""",
        encoding="utf-8",
    )
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())
        agent = _ReplanningAgent()
        runtime = AgentRuntime(agent, browser, config=AgentConfig(max_llm_calls=4))
        result = await runtime.run("Start and finish the workflow.")
        assert result.done
        assert result.completed == ["Start workflow", "Finish workflow"]
        assert result.steps_taken == 2
        assert agent.calls == 3
