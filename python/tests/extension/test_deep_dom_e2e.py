"""Deep and crowded pages must run through the packaged extension boundary."""

import os
from collections.abc import Callable
from time import perf_counter
from urllib.parse import urljoin

import pytest
from playwright.async_api import expect

from browser_agent._types import BrowserAction, ElementRef
from browser_agent.agent.luna_candidates import agent_observation
from browser_agent.agent.safety import ActionRiskPolicy, RiskCategory
from browser_agent.providers.privacy import ProviderBoundary
from extension.scripted_reasoner import ScriptedReasoner
from extension.test_browser_e2e import AttachedHarness, use_scripted_reasoner

pytest_plugins = ("extension.test_browser_e2e",)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BROWSKI_EXTENSION_E2E") != "1",
        reason="set BROWSKI_EXTENSION_E2E=1 to launch a real extension browser",
    ),
]
MAX_PROVIDER_CONTEXT_CHARACTERS = 32_000


@pytest.mark.parametrize("crowded", [False, True])
async def test_sidepanel_observes_and_acts_inside_nested_document(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Callable[[str, object], None],
    crowded: bool,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(target_name="Reveal result", evidence="Nested action verified")
    use_scripted_reasoner(monkeypatch, ProviderBoundary(provider))
    path = "deep-dom.html?crowded=1" if crowded else "deep-dom.html"
    await harness.demo.goto(urljoin(harness.demo.url, path))
    await expect(harness.demo.get_by_role("button", name="Reveal result")).to_be_visible()
    if crowded:
        snapshot = await harness.browser.observe()
        observation = agent_observation(snapshot)
        original_characters = len(observation.model_dump_json(exclude_none=True))
        assert original_characters > MAX_PROVIDER_CONTEXT_CHARACTERS
        target = next(item for item in snapshot.elements if item.accessible_name == "Reveal result")
        risk = ActionRiskPolicy().assess(
            BrowserAction(
                type="click",
                target=ElementRef(ref=target.ref, generation=snapshot.state_generation),
            ),
            snapshot,
            user_goal="Click Reveal result.",
        )
        assert risk.category is not RiskCategory.HIGH, "fixture control must be a non-submit button"
        record_property("original_observation_characters", original_characters)
        record_property("original_observation_elements", len(observation.elements))

    await harness.panel.get_by_label("Task instruction").fill("Click Reveal result.")
    started = perf_counter()
    await harness.panel.get_by_role("button", name="Send task").click()
    await expect(harness.demo.get_by_role("heading", name="Nested action verified")).to_be_visible(
        timeout=120_000
    )
    await expect(harness.panel.get_by_text("Task completed", exact=True)).to_be_visible(
        timeout=120_000
    )
    await expect(harness.panel.get_by_text("Verified browser result", exact=True)).to_be_visible()
    record_property("task_elapsed_ms", round((perf_counter() - started) * 1000))

    assert provider.contexts, "real browser observation must reach the decision provider"
    assert all(
        len(context.model_dump_json(exclude_none=True)) <= MAX_PROVIDER_CONTEXT_CHARACTERS
        for context in provider.contexts
    )
    record_property(
        "provider_context_characters",
        [len(context.model_dump_json(exclude_none=True)) for context in provider.contexts],
    )
    if crowded:
        assert any(context.observation.truncated for context in provider.contexts)
        assert all(
            any(item.name == "Reveal result" for item in context.observation.elements)
            for context in provider.contexts
        )
