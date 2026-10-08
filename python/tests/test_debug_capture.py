"""Public API debug evidence excludes hidden reasoning and transport secrets."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from browser_agent._types import AgentObservation, TaskState, WorkingMemory
from browser_agent.cli.config import ConfigError, load_config
from browser_agent.reasoning import (
    ReasoningContext,
    ReasoningDecision,
    ReasoningOutcome,
    ReasoningPurpose,
)
from browser_agent.reasoning.openai_adapter import OpenAILunaProvider, ReasoningProviderRequestError
from browser_agent.telemetry.debug_log import DebugLogConfig, DebugRecorder


class FakeResponses:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def parse(self, **kwargs: object) -> object:
        _ = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            id="response-fixture",
            model="fixture-model",
            status="completed",
            output_parsed=ReasoningDecision(
                outcome=ReasoningOutcome.ASK_USER, questions=["Choose a form title."]
            ),
            usage=SimpleNamespace(input_tokens=20, output_tokens=10, total_tokens=30),
            output=[
                SimpleNamespace(type="reasoning", encrypted_content="hidden-fixture"),
                SimpleNamespace(
                    type="message",
                    content=[
                        SimpleNamespace(
                            type="output_text", text='{"questions":["Choose a form title."]}'
                        )
                    ],
                ),
            ],
        )


class FakeClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.responses = FakeResponses(error=error)


def _context() -> ReasoningContext:
    return ReasoningContext(
        purpose=ReasoningPurpose.PLAN,
        task=TaskState(task="Create a blank form"),
        memory=WorkingMemory(user_goal="Create a blank form"),
        observation=AgentObservation(url="https://example.test/forms", state_generation=1),
    )


def _events(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / "capture-run" / "events.jsonl").read_text().splitlines()
    ]


async def test_luna_request_response_debug_capture_is_public_and_correlated(tmp_path: Path) -> None:
    recorder = DebugRecorder(DebugLogConfig(enabled=True, directory=tmp_path))
    with recorder.bind("capture-run", "capture-session"):
        await OpenAILunaProvider(FakeClient()).reason(_context())

    events = _events(tmp_path)
    request = events[0]["payload"]
    response = events[1]["payload"]
    assert request["input"]["task"]["task"] == "Create a blank form"
    assert request["call_id"] == response["call_id"]
    assert response["response"]["usage"]["total_tokens"] == 30
    assert response["response"]["output"][0]["content"]["questions"] == ["Choose a form title."]
    assert "hidden-fixture" not in json.dumps(events)


async def test_luna_sdk_error_capture_never_persists_raw_exception_text(tmp_path: Path) -> None:
    recorder = DebugRecorder(DebugLogConfig(enabled=True, directory=tmp_path))
    with recorder.bind("capture-run", "capture-session"):
        with pytest.raises(ReasoningProviderRequestError):
            await OpenAILunaProvider(
                FakeClient(error=RuntimeError("private-error-fixture"))
            ).reason(_context())

    events = _events(tmp_path)
    assert events[-1]["event"] == "provider.error"
    assert events[-1]["payload"]["error_type"] == "RuntimeError"
    assert "private-error-fixture" not in json.dumps(events)


@pytest.mark.parametrize("maximum", [True, 0, 1024 * 1024 * 1024 + 1])
def test_invalid_debug_limits_are_rejected(tmp_path: Path, maximum: int | bool) -> None:
    source = (Path(__file__).parents[1] / "src/browser_agent/cli/default.toml").read_text()
    value = "true" if maximum is True else str(maximum)
    path = tmp_path / "config.toml"
    path.write_text(source.replace("max_session_bytes = 16777216", f"max_session_bytes = {value}"))
    with pytest.raises(ConfigError):
        load_config(path)


def test_legacy_config_without_debug_section_preserves_disabled_default(tmp_path: Path) -> None:
    source = (Path(__file__).parents[1] / "src/browser_agent/cli/default.toml").read_text()
    path = tmp_path / "config.toml"
    path.write_text(source.split("[debug]")[0])
    assert load_config(path).debug.enabled is False
