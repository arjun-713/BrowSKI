"""Product defaults, General budgets, public events and completion contracts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from browser_agent.cli.config import (
    AgentConfig,
    ConfigError,
    ExecutionEngine,
    TextProviderName,
    load_config,
    parse_config,
)
from browser_agent.engines.contracts import EngineEvent, EngineResult, EngineStatus
from browser_agent.engines.general import (
    GeneralConfig,
    _completion,  # pyright: ignore[reportPrivateUsage]
)
from browser_agent.engines.lifecycle import ActionApproval, TaskControl
from browser_agent.extension.engine_tasks import result_extras, timeline_payload


def test_general_product_defaults_and_bounded_config_keys() -> None:
    defaults = AgentConfig(orchestrator="langgraph")
    assert defaults.engine is ExecutionEngine.GENERAL
    assert defaults.text_provider is TextProviderName.OPENAI and defaults.allow_paid_api
    assert (
        defaults.general_max_steps,
        defaults.general_max_calls,
        defaults.general_timeout_seconds,
    ) == (60, 150, 1800)
    assert defaults.general_max_failures == 3 and defaults.general_step_timeout >= 120
    general = GeneralConfig()
    assert (general.max_steps, general.max_calls, general.timeout_seconds) == (60, 150, 1800)
    assert general.max_failures == 3 and general.step_timeout >= 120


@pytest.mark.parametrize(
    "key,value",
    [
        ("max_steps", 0),
        ("max_calls", 501),
        ("timeout_seconds", 7201),
        ("max_failures", 0),
        ("step_timeout", 119),
    ],
)
def test_general_budget_bounds(key: str, value: int) -> None:
    with pytest.raises(ValidationError):
        GeneralConfig.model_validate({key: value})


@pytest.mark.parametrize(
    "key,value",
    [
        ("general_max_steps", 0),
        ("general_max_calls", True),
        ("general_timeout_seconds", 7201),
        ("general_max_failures", 11),
        ("general_step_timeout", 119),
    ],
)
def test_toml_general_budget_validation(key: str, value: object) -> None:
    import tomllib
    from importlib.resources import files

    document = tomllib.loads(files("browser_agent.cli").joinpath("default.toml").read_text())
    document["agent"][key] = value
    with pytest.raises(ConfigError, match=key):
        parse_config(document)


def test_toml_keeps_explicit_fast_choice_and_accepts_old_files() -> None:
    import tomllib
    from importlib.resources import files

    document = tomllib.loads(files("browser_agent.cli").joinpath("default.toml").read_text())
    document["agent"].update(engine="fast", text_provider="disabled", allow_paid_api=False)
    config = parse_config(document)
    assert config.agent.engine is ExecutionEngine.FAST and not config.agent.allow_paid_api
    assert config.agent.general_max_steps == 60
    document["agent"] = {"orchestrator": "langgraph"}
    config = parse_config(document)
    assert config.agent.engine is ExecutionEngine.GENERAL and config.agent.allow_paid_api


def test_panel_event_and_result_fields_are_bounded_and_structured() -> None:
    event = EngineEvent(
        kind="action_started",
        provider="openai",
        label="Clicked “Search”",
        detail="Find the article.",
        page_url="https://example.test/search",
    )
    payload = timeline_payload(
        event, session_id="session", run_id="run", sequence=1, request_id="request"
    )
    assert payload and payload["label"] == event.label and payload["detail"] == event.detail
    assert payload["pageUrl"] == event.page_url and payload["type"] == "ActionStarted"
    result = EngineResult(
        status=EngineStatus.PARTIALLY_COMPLETED,
        provider="openai",
        model="fixture",
        answer="Partial answer",
        verdict_reason="More evidence is needed.",
        steps=3,
        action_count=2,
        generative_calls=4,
        duration_ms=123.6,
    )
    assert result_extras(result) == {
        "answer": "Partial answer",
        "verdict": {"verified": False, "reason": "More evidence is needed."},
        "stats": {"steps": 3, "actions": 2, "modelCalls": 4, "durationMs": 124},
    }
    assert "answer" not in result_extras(result.model_copy(update={"answer": None}))
    for fields in ({"label": "a" * 161}, {"detail": "a" * 501}, {"page_url": "file:///secret"}):
        with pytest.raises(ValidationError):
            EngineEvent.model_validate({"kind": "action_started", "provider": "openai", **fields})
    with pytest.raises(ValueError, match="reason"):
        ActionApproval(action="click", target="Pay", reason="a" * 301)


@pytest.mark.parametrize(
    "done,success,verdict,expected",
    [
        (True, True, True, EngineStatus.COMPLETED),
        (True, True, False, EngineStatus.PARTIALLY_COMPLETED),
        (True, True, None, EngineStatus.PARTIALLY_COMPLETED),
        (True, False, True, EngineStatus.PARTIALLY_COMPLETED),
        (False, None, True, EngineStatus.PARTIALLY_COMPLETED),
    ],
)
def test_done_alone_never_proves_completion(
    done: bool, success: bool | None, verdict: bool | None, expected: EngineStatus
) -> None:
    class History:
        def is_done(self) -> bool:
            return done

        def is_successful(self) -> bool | None:
            return success

        def final_result(self) -> str:
            return "Agent final message"

        def judgement(self) -> dict[str, object] | None:
            return (
                None
                if verdict is None
                else {"verdict": verdict, "failure_reason": "Judge rejected the outcome"}
            )

    status, reason = _completion(cast(Any, History()), None, None, steps=3, max_steps=60, actions=2)
    assert status is expected and reason
    assert reason != "Agent final message", "the answer is not repeated as the verdict"
    if done and success is False:
        # Without any executed action, an agent-reported failure means it was blocked.
        idle, _ = _completion(cast(Any, History()), None, None, steps=1, max_steps=60, actions=0)
        assert idle is EngineStatus.BLOCKED


async def test_missing_key_is_actionable_and_general_dispatch_passes_relay_and_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from browser_agent.engines import general, product

    async def events(event: EngineEvent) -> None:
        pass

    config = load_config()
    config = replace(
        config,
        agent=replace(
            config.agent,
            engine=ExecutionEngine.GENERAL,
            text_provider=TextProviderName.OPENAI,
            allow_paid_api=True,
            general_max_steps=72,
        ),
    )
    monkeypatch.setattr(product, "configured_openai_api_key", lambda: None)
    with pytest.raises(
        product.EngineConfigurationError, match="Add your OpenAI API key in Settings to run tasks."
    ):
        await product.execute_managed_task(
            "Read",
            config,
            start_url=None,
            criteria=None,
            events=events,
            control=TaskControl("general", "openai", events),
        )

    observed: dict[str, Any] = {}

    async def run(goal: str, options: GeneralConfig, **kwargs: Any) -> EngineResult:
        observed.update(kwargs)
        assert options.max_steps == 72 and options.max_calls == 150 and options.max_failures == 3
        return EngineResult(status=EngineStatus.BLOCKED, provider="openai", model="fixture")

    monkeypatch.setattr(product, "configured_openai_api_key", lambda: "offline-only")
    monkeypatch.setattr(general, "run_general", run)
    await product.execute_managed_task(
        "Read",
        config,
        start_url=None,
        criteria=None,
        events=events,
        control=TaskControl("general", "openai", events),
        cdp_url="ws://127.0.0.1:9999/devtools/browser/fixture",
    )
    assert observed["cdp_url"] == "ws://127.0.0.1:9999/devtools/browser/fixture"
