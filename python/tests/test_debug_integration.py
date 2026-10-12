"""Integration checks for opt-in debug capture across runtime boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from browser_agent import AgentDecision
from browser_agent._types import (
    BBox,
    SemanticElement,
    SemanticKind,
    SemanticSnapshot,
    TaskState,
    Viewport,
    WorkingMemory,
)
from browser_agent.agent import Agent, AgentRuntime, LunaDecisionAgent
from browser_agent.reasoning import (
    ReasoningAction,
    ReasoningDecision,
    ReasoningEffort,
    ReasoningOutcome,
)
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder


def _snapshot() -> SemanticSnapshot:
    element = SemanticElement(
        ref="@continue",
        id=12,
        generation=4,
        role="button",
        accessible_name="Continue",
        bbox=BBox(x=100, y=200, width=120, height=40),
        semantic_kind=SemanticKind.BUTTON,
        fingerprint="continue-button",
    )
    return SemanticSnapshot(
        url="https://example.test/form",
        title="Form",
        active_tab="tab-1",
        tabs=["tab-1"],
        viewport=Viewport(width=1280, height=720, device_scale_factor=1.0),
        elements=[element],
        interactive_elements=[element],
        state_generation=4,
        page_fingerprint="form-state",
    )


class FakeBrowser:
    """Supply a deterministic semantic observation without launching Chromium."""

    def __init__(self) -> None:
        self.observations = 0

    async def observe(self) -> SemanticSnapshot:
        self.observations += 1
        return _snapshot()


class AskingUserAgent(Agent):
    async def decide(
        self,
        snapshot: SemanticSnapshot,
        task: TaskState,
        memory: WorkingMemory,
    ) -> AgentDecision:
        _ = snapshot, task, memory
        return AgentDecision(ask_user=["Which result should I open?"])


class FakeReasoningProvider:
    def __init__(self, decision: ReasoningDecision) -> None:
        self.decision = decision

    async def reason(
        self,
        context: Any,
        *,
        model: str,
        effort: ReasoningEffort,
    ) -> ReasoningDecision:
        _ = context, model, effort
        return self.decision


def _events(root: Path, run_id: str) -> list[dict[str, Any]]:
    path = root / run_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


async def test_runtime_debug_records_are_isolated_by_run(tmp_path: Path) -> None:
    debug_root = tmp_path / "debug"
    runtime = AgentRuntime(
        AskingUserAgent(),
        FakeBrowser(),  # type: ignore[arg-type]
        debug_config=DebugLogConfig(enabled=True, directory=debug_root),
    )

    first = await runtime.run("Open the first result", run_id="first-debug-run")
    second = await runtime.run("Open the second result", run_id="second-debug-run")

    assert first.status == "awaiting_user"
    assert second.status == "awaiting_user"

    first_events = _events(debug_root, "first-debug-run")
    second_events = _events(debug_root, "second-debug-run")

    assert {event["run_id"] for event in first_events} == {"first-debug-run"}
    assert {event["run_id"] for event in second_events} == {"second-debug-run"}
    assert {event["session_id"] for event in first_events} == {runtime.session_id}
    assert {event["session_id"] for event in second_events} == {runtime.session_id}

    first_prompt = next(event for event in first_events if event["event"] == "task.prompt")
    second_prompt = next(event for event in second_events if event["event"] == "task.prompt")
    assert first_prompt["payload"]["prompt"] == "Open the first result"
    assert second_prompt["payload"]["prompt"] == "Open the second result"

    for run_events in (first_events, second_events):
        names = [event["event"] for event in run_events]
        assert "browser.observation" in names
        assert "runtime.event" in names
        assert "task.result" in names


async def test_candidate_mismatch_is_logged_without_changing_rejection(
    tmp_path: Path,
) -> None:
    debug_root = tmp_path / "debug"
    recorder = DebugRecorder(DebugLogConfig(enabled=True, directory=debug_root))
    provider = FakeReasoningProvider(
        ReasoningDecision(
            outcome=ReasoningOutcome.NEXT_ACTION,
            summary="Continue the application form.",
            action=ReasoningAction(
                type="scroll",
                dy=123,
            ),
        )
    )
    agent = LunaDecisionAgent(None, provider)
    task = TaskState(
        task="Continue the application",
        plan_initialized=True,
        milestones=["Continue the application"],
        current_subgoal="Continue the application",
        run_id="candidate-debug-run",
    )

    with recorder.bind("candidate-debug-run", "candidate-debug-session"):
        decision = await agent.decide(
            _snapshot(),
            task,
            WorkingMemory(user_goal="Continue the application"),
        )

    assert decision.action is None
    assert decision.ask_user

    events = _events(debug_root, "candidate-debug-run")
    validation = next(
        event for event in events if event["event"] == "decision.candidate_validation"
    )
    payload = validation["payload"]
    assert payload["accepted"] is False
    assert payload["reason"] == "signature_mismatch"
    assert any(comparison["differing_fields"] == ["dy"] for comparison in payload["comparisons"])
