"""General searches with the configured engine unless the task names one."""

from __future__ import annotations

import pytest

from browser_agent.cli.config import ConfigError, SearchEngine, parse_config
from browser_agent.engines.general_tools import InteractionPolicy, search_engine_for
from browser_agent.reasoning.contracts import ReasoningEffort


@pytest.mark.parametrize(
    ("goal", "configured", "expected"),
    [
        ("Compare Mac mini prices on Apple and Amazon", "google", "google"),
        ("Search on Bing for the Eiffel Tower height", "google", "bing"),
        ("Use DuckDuckGo to find the release notes", "google", "duckduckgo"),
        ("Compare Google and Bing results for my name", "google", "google"),
        ("Find the cheapest flight", "bing", "bing"),
    ],
)
def test_search_engine_follows_task_then_configuration(
    goal: str, configured: str, expected: str
) -> None:
    policy = InteractionPolicy(goal=goal, model_authored=True, search_engine=configured)
    assert search_engine_for(policy) == expected


def _document(agent: dict[str, object]) -> dict[str, object]:
    import tomllib
    from pathlib import Path

    import browser_agent.cli as cli

    defaults = tomllib.loads((Path(cli.__file__).parent / "default.toml").read_text())
    return {**defaults, "agent": {**defaults["agent"], **agent}}


def test_reasoning_effort_defaults_to_low_and_validates() -> None:
    assert parse_config(_document({})).agent.general_reasoning_effort is ReasoningEffort.LOW
    high = parse_config(_document({"general_reasoning_effort": "high"}))
    assert high.agent.general_reasoning_effort is ReasoningEffort.HIGH
    with pytest.raises(ConfigError, match="general_reasoning_effort"):
        parse_config(_document({"general_reasoning_effort": "maximum"}))


def test_search_engine_defaults_to_google_and_validates() -> None:
    assert parse_config(_document({})).agent.general_search_engine is SearchEngine.GOOGLE
    bing = parse_config(_document({"general_search_engine": "bing"}))
    assert bing.agent.general_search_engine is SearchEngine.BING
    with pytest.raises(ConfigError, match="general_search_engine"):
        parse_config(_document({"general_search_engine": "yahoo"}))
