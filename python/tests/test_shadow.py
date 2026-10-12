"""Tests for bounded, non-blocking Laya shadow comparisons."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from browser_agent.agent.shadow import ShadowComparisonEvent, ShadowDecisionManager
from browser_agent.decisions.base import (
    DecisionAnswer,
    DecisionKind,
    DecisionProvider,
    DecisionQuestion,
    DecisionResult,
)
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder


class FixedShadowProvider(DecisionProvider):
    name = "fake-laya"

    def __init__(self, value: str, accepted: bool | None = None) -> None:
        self.value = value
        self.accepted = accepted
        self.calls: list[tuple[object, Mapping[str, str | None]]] = []

    async def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        question = questions["decision"]
        assert question.kind == DecisionKind.CHOICE
        assert isinstance(question.criteria, Mapping)
        self.calls.append((state, question.criteria))
        return DecisionResult(
            provider=self.name,
            model="fake",
            answers={
                "decision": DecisionAnswer(
                    kind=DecisionKind.CHOICE,
                    value=self.value,
                    accepted=self.accepted,
                    confidence_raw=0.8,
                    confidence_calibrated=0.7,
                    raw={"confidence": 0.2, "answer_confidence": 0.8},
                )
            },
        )


class BlockingShadowProvider(FixedShadowProvider):
    def __init__(self) -> None:
        super().__init__("candidate-a")
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def evaluate(
        self,
        state: str | Mapping[str, Any],
        questions: Mapping[str, DecisionQuestion],
    ) -> DecisionResult:
        self.started.set()
        await self.release.wait()
        return await super().evaluate(state, questions)


def _options() -> dict[str, str]:
    return {"candidate-a": "Click the provided button", "candidate-b": "Escalate"}


async def test_shadow_records_choice_when_provider_threshold_is_unconfigured() -> None:
    provider = FixedShadowProvider("candidate-a", accepted=None)
    events: list[ShadowComparisonEvent] = []
    manager = ShadowDecisionManager(provider, telemetry=events.append)

    scheduled = manager.schedule_choice(
        {
            "task": "Find the warranty",
            "current_subgoal": "Open warranty evidence",
            "observation": {"elements": [{"text": "private full snapshot"}]},
        },
        _options(),
        "candidate-a",
        run_id="run-7",
        step=3,
    )
    await asyncio.sleep(0)
    await manager.close()

    assert scheduled is True
    assert len(provider.calls) == 1
    assert events[0].outcome == "success"
    assert events[0].laya_choice == "candidate-a"
    assert events[0].agreement is True
    assert events[0].raw_confidence == 0.2
    assert events[0].answer_confidence == 0.8
    assert events[0].normalized_confidence == 0.7
    sent_state = provider.calls[0][0]
    assert isinstance(sent_state, Mapping)
    assert "observation" not in sent_state
    typed_state = cast(Mapping[str, Any], sent_state)
    assert "private full snapshot" not in str(typed_state)


async def test_shadow_skips_when_one_comparison_is_in_flight() -> None:
    provider = BlockingShadowProvider()
    events: list[ShadowComparisonEvent] = []
    manager = ShadowDecisionManager(provider, telemetry=events.append)

    assert manager.schedule_choice({}, _options(), "candidate-a", run_id="r", step=1)
    await provider.started.wait()

    assert not manager.schedule_choice({}, _options(), "candidate-b", run_id="r", step=2)

    await manager.close()

    assert events[-1].outcome == "cancelled"
    assert events[0].outcome == "skipped_busy"


async def test_shadow_request_is_bounded_without_dropping_candidates() -> None:
    options = {
        f"candidate-{index}": "Inspect this supplied browser action. " * 10 for index in range(16)
    }
    provider = FixedShadowProvider("candidate-0")
    manager = ShadowDecisionManager(provider, max_context_characters=2_048)

    assert manager.schedule_choice(
        {
            "task": "task context " * 300,
            "current_subgoal": "subgoal context " * 300,
            "recent_outcome": "recent outcome " * 300,
        },
        options,
        "candidate-0",
        run_id="r",
        step=1,
    )
    await asyncio.sleep(0.01)
    await manager.close()

    raw_state, sent_options = provider.calls[0]
    state = cast(Mapping[str, Any], raw_state)
    assert isinstance(state, Mapping)
    request: dict[str, object] = {
        "state": state,
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": (
                    "Choose one supplied candidate for shadow comparison only. "
                    "Do not create or authorize an action."
                ),
                "criteria": sent_options,
            }
        },
    }
    assert len(json.dumps(request, ensure_ascii=True)) <= 2_048
    assert set(sent_options) == set(options)


async def test_shadow_event_is_captured_by_the_bound_debug_session(
    tmp_path: Path,
) -> None:
    recorder = DebugRecorder(DebugLogConfig(enabled=True, directory=tmp_path))
    provider = FixedShadowProvider("candidate-a", accepted=None)
    manager = ShadowDecisionManager(provider)

    with recorder.bind("shadow-run", "shadow-session"):
        manager.schedule_choice(
            {"task": "Find the warranty"},
            _options(),
            "candidate-a",
            run_id="shadow-run",
            step=4,
        )
        await asyncio.sleep(0.01)
        await manager.close()

    events = [
        json.loads(line)
        for line in (tmp_path / "shadow-run" / "events.jsonl").read_text().splitlines()
    ]
    assert len(events) == 1
    assert events[0]["event"] == "agent.shadow_comparison"
    assert events[0]["step"] == 4
    assert events[0]["payload"]["answer_confidence"] == 0.8
    assert "Find the warranty" not in json.dumps(events)


async def test_shadow_timeout_stops_future_attempts() -> None:
    class SlowProvider(BlockingShadowProvider):
        async def evaluate(
            self,
            state: str | Mapping[str, Any],
            questions: Mapping[str, DecisionQuestion],
        ) -> DecisionResult:
            await asyncio.sleep(1)
            return await super().evaluate(state, questions)

    provider = SlowProvider()
    events: list[ShadowComparisonEvent] = []
    manager = ShadowDecisionManager(provider, timeout_ms=1, telemetry=events.append)

    manager.schedule_choice({}, _options(), "candidate-a", run_id="r", step=1)
    await asyncio.sleep(0.01)
    await manager.close()

    assert events[0].outcome == "timeout"
    assert not manager.schedule_choice({}, _options(), "candidate-a", run_id="r", step=2)
    assert events[-1].outcome == "skipped_after_timeout"
