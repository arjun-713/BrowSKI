"""M4 graph tests use only local fixtures and a deterministic fake agent."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from browser_agent import AgentDecision, BrowserAction, BrowserSession, ElementRef
from browser_agent._types import SemanticSnapshot, TaskState, WorkingMemory
from browser_agent.agent import Agent, AgentConfig, AgentRuntime
from browser_agent.agent.events import RuntimeEvent, RuntimeEventType
from browser_agent.decisions import (
    DecisionAnswer,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.persistence import SQLiteRunMetadataStore
from browser_agent.persistence.run_metrics import RunMetrics

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


class BlockingNavigationAgent(Agent):
    def __init__(self) -> None:
        self.deciding = asyncio.Event()
        self.release_decision = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = task, memory
        self.deciding.set()
        try:
            await self.release_decision.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        if snapshot.url == "about:blank":
            return AgentDecision(action=BrowserAction(type="navigate", url=FIXTURE.as_uri()))
        return AgentDecision(done=True, result_summary="Fixture opened.")


class AskingUserAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        return AgentDecision(ask_user=["Which result should I open?"])


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


async def test_runtime_emits_content_minimal_timeline_events() -> None:
    events: list[RuntimeEvent] = []

    async def capture(event: RuntimeEvent) -> None:
        events.append(event)

    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(FormAgent(), browser, event_sink=capture)
        result = await runtime.run("Open the signup fixture and accept terms.", run_id="trace-run")

    assert result.done
    assert events[0].type == RuntimeEventType.RUN_STARTED
    assert events[-1].type == RuntimeEventType.RUN_COMPLETED
    event_types = {event.type for event in events}
    assert RuntimeEventType.OBSERVATION_COMPLETED in event_types
    assert RuntimeEventType.DECISION_MADE in event_types
    assert RuntimeEventType.ACTION_STARTED in event_types
    assert RuntimeEventType.ACTION_COMPLETED in event_types
    assert RuntimeEventType.VERIFICATION_COMPLETED in event_types
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert all(event.run_id == "trace-run" for event in events)
    assert all("signup fixture" not in str(event.to_protocol_payload()) for event in events)


async def test_trace_sink_failure_does_not_interrupt_browser_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def broken_sink(_event: RuntimeEvent) -> None:
        raise RuntimeError("sensitive trace transport detail")

    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(FormAgent(), browser, event_sink=broken_sink)
        result = await runtime.run("Open the fixture", run_id="trace-disconnect")

    assert result.done
    assert "trace consumer failed" in caplog.text
    assert "sensitive trace transport detail" not in caplog.text


async def test_pause_checkpoints_before_action_and_resume_continues() -> None:
    agent = BlockingNavigationAgent()
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(agent, browser)
        running = asyncio.create_task(runtime.run("Open the fixture", run_id="pause-run"))
        await agent.deciding.wait()
        runtime.pause("pause-run")
        agent.release_decision.set()

        paused = await running

        assert paused.status == "paused"
        assert "Paused" in (paused.result_summary or "")
        assert (await browser.observe()).url == "about:blank"

        resumed = await runtime.resume("pause-run")

        assert resumed.done
        assert resumed.status == "completed"
        assert (await browser.observe()).url == FIXTURE.as_uri()


async def test_sqlite_pause_resume_does_not_authorize_high_risk_action(tmp_path: Path) -> None:
    fixture = tmp_path / "pause-confirmation.html"
    fixture.write_text(
        """<!doctype html>
<html lang="en"><head><title>Review order</title></head>
<body><form><input name="reference" value="synthetic">
<button type="submit">Submit order</button></form></body></html>""",
        encoding="utf-8",
    )

    class DelayedSubmitAgent(SubmitFixtureAgent):
        def __init__(self, url: str) -> None:
            super().__init__(url)
            self.deciding = asyncio.Event()
            self.release = asyncio.Event()

        async def decide(
            self, snapshot: SemanticSnapshot, task: TaskState, memory: WorkingMemory
        ) -> AgentDecision:
            self.deciding.set()
            await self.release.wait()
            return await super().decide(snapshot, task, memory)

    agent = DelayedSubmitAgent(fixture.as_uri())
    database = tmp_path / "pause.sqlite"
    async with BrowserSession.launch() as browser:
        await browser.navigate(fixture.as_uri())
        async with AgentRuntime.open_sqlite(agent, browser, database=database) as runtime:
            running = asyncio.create_task(runtime.run("Submit order", run_id="paused-order"))
            await agent.deciding.wait()
            runtime.pause("paused-order")
            agent.release.set()
            assert (await running).status == "paused"

        # Reconstruct the graph and controls from SQLite, keeping browser truth live.
        async with AgentRuntime.open_sqlite(agent, browser, database=database) as reopened:
            pending = await reopened.resume("paused-order")
            assert pending.status == "pending_confirmation"
            assert (await browser.observe()).title == "Review order"
            with pytest.raises(ValueError, match="explicit confirmation"):
                await reopened.resume("paused-order")
            denied = await reopened.resume_with_confirmation("paused-order", approved=False)
            assert denied.status == "failed"
            assert (await browser.observe()).title == "Review order"


async def test_stop_while_deciding_does_not_execute_the_pending_action() -> None:
    agent = BlockingNavigationAgent()
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(agent, browser)
        running = asyncio.create_task(runtime.run("Open the fixture", run_id="stop-run"))
        await agent.deciding.wait()

        stop_request = await runtime.stop("stop-run")
        stopped = await running

        assert stop_request.status == "running"
        assert stopped.status == "stopped"
        assert agent.cancelled.is_set()
        assert "Stopped" in (stopped.result_summary or "")
        assert (await browser.observe()).url == "about:blank"


async def test_stop_during_action_waits_for_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = BlockingNavigationAgent()
    async with BrowserSession.launch() as browser:
        action_started = asyncio.Event()
        release_action = asyncio.Event()
        original_act = browser.act

        async def delayed_act(
            action: BrowserAction,
            tab_id: str | None = None,
        ) -> dict[str, Any]:
            action_started.set()
            await release_action.wait()
            return await original_act(action, tab_id)

        monkeypatch.setattr(browser, "act", delayed_act)
        runtime = AgentRuntime(agent, browser)
        agent.release_decision.set()
        running = asyncio.create_task(runtime.run("Open the fixture", run_id="stop-in-flight"))
        await action_started.wait()

        stop_request = await runtime.stop("stop-in-flight")
        release_action.set()
        stopped = await running

        assert stop_request.status == "running"
        assert stopped.status == "stopped"
        assert stopped.steps_taken == 1
        assert (await browser.observe()).url == FIXTURE.as_uri()


async def test_stop_from_paused_checkpoint_is_terminal() -> None:
    agent = BlockingNavigationAgent()
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(agent, browser)
        running = asyncio.create_task(runtime.run("Open the fixture", run_id="paused-stop"))
        await agent.deciding.wait()
        runtime.pause("paused-stop")
        agent.release_decision.set()
        paused = await running

        stopped = await runtime.stop("paused-stop")

        assert paused.status == "paused"
        assert stopped.status == "stopped"
        assert (await browser.observe()).url == "about:blank"


async def test_stop_while_waiting_for_user_persists_terminal_status() -> None:
    async with BrowserSession.launch() as browser:
        runtime = AgentRuntime(AskingUserAgent(), browser)
        waiting = await runtime.run("Open a result", run_id="awaiting-user")

        stopped = await runtime.stop("awaiting-user")
        checkpoint = await runtime.graph.aget_state(
            {"configurable": {"thread_id": "awaiting-user"}}
        )

        assert waiting.status == "awaiting_user"
        assert stopped.status == "stopped"
        assert checkpoint.values["status"] == "stopped"


async def test_sqlite_runtime_records_safe_run_metadata(tmp_path: Path) -> None:
    database = tmp_path / "metadata.sqlite3"
    async with BrowserSession.launch() as browser:
        async with AgentRuntime.open_sqlite(
            CompleteAfterObserveAgent(),
            browser,
            database=database,
        ) as runtime:
            result = await runtime.run("Navigate then inspect", run_id="metadata-run")

    records = await SQLiteRunMetadataStore(database).list_runs()

    assert result.status == "completed"
    assert len(records) == 1
    assert records[0].run_id == "metadata-run"
    assert records[0].status == "completed"
    assert records[0].steps == result.steps_taken
    assert records[0].metrics.action_count == 1
    assert records[0].metrics.task_duration_ms >= 0
    reopened = SQLiteRunMetadataStore(database)
    assert (await reopened.load_metrics("metadata-run")).action_count == 1


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
    assert last_event["semantic_snapshot_bytes"] > 0
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
            assert first.run_metadata_store is not None
            await first.run_metadata_store.record_metrics(
                "resume-test",
                RunMetrics(action_count=7, luna_calls=3, luna_low_effort_calls=3),
                event_at="2026-10-08T00:00:00+00:00",
            )

        async with AgentRuntime.open_sqlite(
            CompleteAfterObserveAgent(), browser, database
        ) as resumed_runtime:
            completed = await resumed_runtime.resume("resume-test")

        assert completed.done
        assert completed.task == "Finish after observing."
        resumed_metrics = await SQLiteRunMetadataStore(database).load_metrics("resume-test")
        assert resumed_metrics.action_count == 8
        assert resumed_metrics.luna_calls == 3


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
        confirmation = await runtime.pending_confirmation_details("submit-denied")
        assert confirmation["action"] == "click"
        assert confirmation["target"] == "Submit order"
        assert confirmation["reason"] == "policy requires confirmation"
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
