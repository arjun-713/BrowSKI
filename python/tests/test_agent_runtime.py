"""M4 graph tests use only local fixtures and a deterministic fake agent."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime
from browser_agent.decisions import (
    DecisionAnswer,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)

pytestmark = pytest.mark.asyncio

FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/m3/form-flow.html"
CLICK_FIXTURE = Path(__file__).resolve().parents[2] / "tests/fixtures/m3/click-success.html"


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
        _ = task, memory
        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=FIXTURE.as_uri()))
        return AgentDecision(done=True, result_summary="No action required.")


class ClaimDoneWithoutEvidenceAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        return AgentDecision(done=True, result_summary="Trust me, done.")


class RepeatedFailureAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=FIXTURE.as_uri()))
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(ref="@missing", id=999_999, generation=snapshot.state_generation),
            )
        )


class EscalationRecoveryProvider(DecisionProvider):
    name = "fake-recovery"

    def __init__(self) -> None:
        self.states: list[str | Mapping[str, Any]] = []

    async def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        self.states.append(state)
        return DecisionResult(
            provider=self.name,
            model="fake",
            answers={
                key: DecisionAnswer(kind=question.kind, value="escalate")
                for key, question in questions.items()
            },
        )


class SubmitFixtureAgent(Agent):
    def __init__(self, fixture_url: str) -> None:
        self.fixture_url = fixture_url

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if "Order submitted" in (snapshot.text_excerpt or ""):
            return AgentDecision(done=True, result_summary="The fixture confirmed submission.")
        if snapshot.url != self.fixture_url:
            return AgentDecision(action=BrowserAction(type="navigate", url=self.fixture_url))

        submit_element = next(
            element
            for element in snapshot.elements
            if element.accessible_name == "Submit order" or element.text == "Submit order"
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(
                    ref=submit_element.ref,
                    id=submit_element.id,
                    generation=submit_element.generation,
                ),
            )
        )


class LongHorizonAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=CLICK_FIXTURE.as_uri()))
        if task.steps_taken >= 11:
            return AgentDecision(done=True, result_summary="Ten verified clicks completed.")
        button = next(
            element
            for element in snapshot.elements
            if element.accessible_name == "Increment" or element.text == "Increment"
        )
        return AgentDecision(
            action=BrowserAction(
                type="click",
                target=ElementRef(ref=button.ref, id=button.id, generation=button.generation),
            )
        )


async def test_graph_executes_verified_actions_on_local_fixture() -> None:
    task = TaskState(
        task="Open the signup fixture and accept terms.",
        recovery_streak=3,
        replan_count=1,
    )
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(FormAgent(), browser)
        result = await runtime.run(task)

        assert result.done
        assert result.steps_taken == 2
        assert result.llm_calls == 3
        assert result.recovery_streak == 0
        assert result.replan_count == 0
        snapshot = await browser.observe()
        checkbox = next(el for el in snapshot.elements if el.role == "checkbox")
        assert "checked" in checkbox.state


async def test_long_horizon_counts_text_only_changes_as_progress() -> None:
    task = TaskState(task="Click ten times", required_evidence=["clicked 10 times"])
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(
            LongHorizonAgent(),
            browser,
            config=AgentConfig(max_steps=20, max_history_events=5),
        )
        completed = await runtime.run(task, run_id="long-horizon")
        state = await runtime.graph.aget_state({"configurable": {"thread_id": "long-horizon"}})

    assert completed.done
    assert completed.steps_taken == 11
    assert completed.stagnant_steps == 0
    assert len(state.values["action_history"]) <= 5
    snapshot_checkpoint = state.values["snapshot"]
    assert snapshot_checkpoint is not None
    assert set(snapshot_checkpoint) == {
        "url",
        "title",
        "active_tab",
        "page_fingerprint",
        "state_generation",
        "element_count",
    }
    assert "elements" not in snapshot_checkpoint
    last_event = state.values["action_history"][-1]
    assert last_event["run_id"] == "long-horizon"
    assert last_event["step_number"] == completed.steps_taken
    assert last_event["observation_size"]["before_elements"] >= 0
    assert last_event["observation_size"]["after_elements"] >= 0
    assert set(last_event["timings"]).issubset(
        {
            "pre_observation_ms",
            "target_resolution_ms",
            "action_execution_ms",
            "mechanical_recovery_ms",
            "settle_ms",
            "post_observation_ms",
            "delta_ms",
            "verification_ms",
        }
    )


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


async def test_model_done_claim_without_verified_browser_evidence_is_rejected() -> None:
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(ClaimDoneWithoutEvidenceAgent(), browser)
        result = await runtime.run("Claim completion without browser evidence.")

    assert not result.done


async def test_system_one_recovery_classification_receives_only_failure_kind() -> None:
    async with BrowserSession.launch() as browser:
        provider = EscalationRecoveryProvider()
        runtime = AgentRuntime(RepeatedFailureAgent(), browser, decision_provider=provider)
        result = await runtime.run("A sensitive task description must stay local.")

    assert result.status == "awaiting_user"
    assert not result.done
    assert result.recovery_history[-1]["classification"] == "escalate"
    assert provider.states == [{"failure_kind": "EXECUTION"}]


async def test_repeated_failure_stops_at_the_recovery_budget() -> None:
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(
            RepeatedFailureAgent(),
            browser,
            config=AgentConfig(max_recovery_actions=1, max_stagnant_steps=2),
        )
        result = await runtime.run("Recover from a repeated invalid action.")

    assert result.status == "awaiting_user"
    assert result.recovery_count == 2
    assert result.steps_taken <= 3
    assert len(result.recovery_history) == 2


async def test_high_risk_submit_suspends_until_explicit_confirmation(tmp_path: Path) -> None:
    fixture = tmp_path / "submit-confirmation.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Order</title></head>
<body><h1 id="status">Review order</h1>
<form id="order"><button type="submit">Submit order</button></form>
<script>
document.querySelector('#order').addEventListener('submit', (event) => {
  event.preventDefault();
  document.querySelector('#status').textContent = 'Order submitted';
});
</script></body></html>""",
        encoding="utf-8",
    )
    fixture_url = fixture.as_uri()
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(SubmitFixtureAgent(fixture_url), browser)

        denied = await runtime.run("Submit the signup form.", run_id="submit-denied")
        assert denied.status == "pending_confirmation"
        denied_result = await runtime.resume_with_confirmation("submit-denied", approved=False)
        assert denied_result.status == "failed"
        assert "denied" in (denied_result.result_summary or "")
        assert "Review order" in ((await browser.observe()).text_excerpt or "")

        pending = await runtime.run("Submit the signup form.", run_id="submit-approved")
        assert pending.status == "pending_confirmation"
        assert pending.run_id == "submit-approved"
        completed = await runtime.resume_with_confirmation("submit-approved", approved=True)
        assert completed.done
        assert completed.status == "completed"
        assert "Order submitted" in ((await browser.observe()).text_excerpt or "")
