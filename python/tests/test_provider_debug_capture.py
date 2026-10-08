"""Provider debug capture keeps useful payloads while removing private data."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from browser_agent._types import AgentObservation, PrunedElement
from browser_agent.decisions import DecisionKind, DecisionQuestion, LayaProvider
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder
from browser_agent.vision import (
    OpenAILunaVisionProvider,
    ScreenshotMetadata,
    SemanticTargetMetadata,
    VisionOutcome,
    VisionRequest,
)


def _read_events(directory: Path, run_id: str) -> list[dict[str, Any]]:
    path = directory / run_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def _debug_recorder(directory: Path) -> DebugRecorder:
    return DebugRecorder(DebugLogConfig(enabled=True, directory=directory))


class FakeLayaModel:
    def predict(self, state: object, questions: object) -> dict[str, object]:
        _ = state, questions
        return {
            "model": "fixture-laya",
            "answers": {"choice": {"choice": "continue", "confidence": 0.9}},
            "api_key": "laya-secret-marker",
        }


async def test_laya_debug_capture_records_request_and_sanitized_response(
    tmp_path: Path,
) -> None:
    recorder = _debug_recorder(tmp_path / "debug")
    provider = LayaProvider(FakeLayaModel())
    questions = {
        "choice": DecisionQuestion(
            DecisionKind.CHOICE,
            "Choose one supplied option",
            {"continue": None, "stop": None},
        )
    }
    state = {"page": "form", "password": "laya-secret-marker"}

    with recorder.bind("laya-debug-run", "laya-debug-session"):
        await provider.evaluate(state, questions)

    events = _read_events(tmp_path / "debug", "laya-debug-run")
    request = next(event for event in events if event["event"] == "provider.request")
    response = next(event for event in events if event["event"] == "provider.response")
    request_payload = request["payload"]
    response_payload = response["payload"]

    assert request_payload["provider"] == "laya"
    assert request_payload["operation"] == "evaluate"
    assert request_payload["request"]["questions"]["choice"]["instructions"]
    assert request_payload["request"]["state"]["password"] == "[REDACTED]"
    assert response_payload["provider"] == "laya"
    assert response_payload["operation"] == "evaluate"
    assert response_payload["elapsed_ms"] >= 0
    assert response_payload["input_tokens"] is None
    assert response_payload["response"]["answers"]["choice"]
    assert response_payload["response"]["api_key"] == "[REDACTED]"
    assert "laya-secret-marker" not in json.dumps(events)
    assert request_payload["call_id"] == response_payload["call_id"]


class FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp_fixture",
            model="gpt-6-luna",
            status="completed",
            usage=SimpleNamespace(input_tokens=23, output_tokens=7, total_tokens=30),
            output_parsed={
                "outcome": "interpretation",
                "summary": "The control is visible.",
                "target_ref": None,
                "confidence": 0.9,
            },
            output=[
                SimpleNamespace(
                    type="reasoning",
                    summary=["hidden-reasoning-marker"],
                ),
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text",
                            text='{"summary":"The control is visible."}',
                        )
                    ],
                ),
            ],
        )


def _vision_request() -> VisionRequest:
    observation = AgentObservation(
        url="https://example.test/form",
        title="Form",
        state_generation=3,
        elements=[PrunedElement(ref="@continue", role="button", name="Continue")],
    )
    return VisionRequest(
        task="Find the continue button",
        observation=observation,
        screenshot=b"vision-private-image-marker",
        mime_type="image/png",
        metadata=ScreenshotMetadata(
            viewport_width=800,
            viewport_height=600,
            active_tab="tab-private",
            state_generation=3,
        ),
        targets=[SemanticTargetMetadata(ref="@continue", role="button", name="Continue")],
    )


async def test_vision_debug_capture_omits_screenshot_and_hidden_reasoning(
    tmp_path: Path,
) -> None:
    recorder = _debug_recorder(tmp_path / "debug")
    responses = FakeResponses()
    provider = OpenAILunaVisionProvider(
        SimpleNamespace(responses=responses),  # type: ignore[arg-type]
    )

    with recorder.bind("vision-debug-run", "vision-debug-session"):
        result = await provider.interpret(_vision_request())

    events = _read_events(tmp_path / "debug", "vision-debug-run")
    request = next(event for event in events if event["event"] == "provider.request")
    response = next(event for event in events if event["event"] == "provider.response")
    serialized_events = json.dumps(events)

    assert result.outcome == VisionOutcome.INTERPRETATION
    assert request["payload"]["operation"] == "vision_interpret"
    assert request["payload"]["store"] is False
    assert "structured finding" in request["payload"]["instructions"]
    assert request["payload"]["response_schema"]["title"] == "VisionInterpretation"
    assert request["payload"]["capture_metadata"] == {
        "mime_type": "image/png",
        "byte_length": len(b"vision-private-image-marker"),
    }
    assert "vision-private-image-marker" not in serialized_events
    assert "aW1hZ2U" not in serialized_events
    assert "hidden-reasoning-marker" not in serialized_events
    assert response["payload"]["response"]["usage"]["input_tokens"] == 23
    assert response["payload"]["response"]["output"] == [
        {
            "type": "output_text",
            "content": {"summary": "The control is visible."},
        }
    ]
    assert request["payload"]["call_id"] == response["payload"]["call_id"]
    assert responses.calls[0]["store"] is False
