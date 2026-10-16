"""Deterministic reliability scenarios over the real attached extension path."""

from __future__ import annotations

import asyncio
import os
from importlib import import_module
from typing import Any

import pytest
from playwright.async_api import expect

from browser_agent._types import BrowserAction, ElementRef, SemanticSnapshot
from browser_agent.cli.config import BrowskiConfig
from browser_agent.extension.service import ExtensionBridgeService
from browser_agent.reasoning import ReasoningProvider
from browser_agent.session import BrowserSession
from extension.scripted_reasoner import ScriptedReasoner
from extension.test_browser_e2e import AttachedHarness

pytest_plugins = ("extension.test_browser_e2e",)
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("BROWSKI_EXTENSION_E2E") != "1",
        reason="set BROWSKI_EXTENSION_E2E=1 to launch a real extension browser",
    ),
]

# The first three tests drive BrowserSession directly (Mode B local runtime).
# The final two submit/control work through the side panel (Mode C extension).


async def _click_named(
    browser: BrowserSession,
    name: str,
) -> tuple[dict[str, Any], SemanticSnapshot]:
    snapshot = await browser.observe()
    element = next(item for item in snapshot.elements if item.accessible_name == name)
    outcome = await browser.act(
        BrowserAction(
            type="click",
            target=ElementRef(
                ref=element.ref,
                id=element.id,
                generation=snapshot.state_generation,
            ),
        )
    )
    assert outcome["verification"]["status"] == "SUCCESS", outcome
    return outcome, await browser.observe()


def _install_reasoning_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: ReasoningProvider,
) -> None:
    def create_provider(_config: BrowskiConfig) -> ReasoningProvider:
        return provider

    cli_module = import_module("browser_agent.cli.main")
    monkeypatch.setattr(cli_module, "create_luna_reasoning_provider", create_provider)


async def _install_reliability_page(harness: AttachedHarness) -> None:
    await harness.demo.goto(f"{harness.demo.url}extension-reliability.html")
    await expect(
        harness.demo.get_by_role("heading", name="BROWSKI extension reliability fixture")
    ).to_be_visible()
    observed = await harness.browser.observe()
    assert "BROWSKI extension reliability fixture" in (observed.title or "")


async def test_mode_b_attached_runtime_reobserves_after_spa_rerender(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    await _install_reliability_page(harness)
    before = await harness.browser.observe()
    assert any(item.accessible_name == "Start dynamic stage" for item in before.elements)

    _, after_render = await _click_named(harness.browser, "Start dynamic stage")

    assert any(
        item.accessible_name == "Continue after SPA rerender" for item in after_render.elements
    )
    assert not any(item.accessible_name == "Start dynamic stage" for item in after_render.elements)

    _, completed = await _click_named(harness.browser, "Continue after SPA rerender")

    assert any(item.text == "Dynamic task completed." for item in completed.elements)
    await expect(harness.demo.get_by_role("status")).to_have_text("Dynamic task completed.")


async def test_mode_b_attached_runtime_recovers_from_controlled_overlay(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    await _install_reliability_page(harness)
    await harness.demo.evaluate("window.renderRecoveryFixture()")
    await _click_named(harness.browser, "Show recoverable overlay")
    blocked = await harness.browser.observe()
    target = next(
        item for item in blocked.elements if item.accessible_name == "Complete task after recovery"
    )
    assert not target.interactable
    assert any(item.accessible_name == "Dismiss blocking overlay" for item in blocked.elements)

    _, recovered = await _click_named(harness.browser, "Dismiss blocking overlay")

    target_after_recovery = next(
        item
        for item in recovered.elements
        if item.accessible_name == "Complete task after recovery"
    )
    assert target_after_recovery.interactable
    _, completed = await _click_named(harness.browser, "Complete task after recovery")

    assert any(item.text == "Recovery task completed." for item in completed.elements)
    await expect(harness.demo.get_by_role("status")).to_have_text("Recovery task completed.")


async def test_mode_b_attached_runtime_completes_ten_verified_actions(
    attached_harness: AttachedHarness,
) -> None:
    harness = attached_harness
    await _install_reliability_page(harness)
    await harness.demo.evaluate("window.renderJourneyFixture()")
    verified_actions: list[dict[str, Any]] = []

    for stage in range(1, 11):
        outcome, _ = await _click_named(
            harness.browser,
            f"Advance to journey stage {stage}",
        )
        verified_actions.append(outcome)

    assert len(verified_actions) == 10
    assert all(item["verification"]["status"] == "SUCCESS" for item in verified_actions)
    await expect(harness.demo.get_by_role("status")).to_have_text(
        "Journey complete after ten verified actions."
    )


async def test_mode_c_extension_reload_during_decision_terminates_without_action(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(
        target_name="Continue to role details",
        evidence="2. Role details",
        blocked=True,
    )
    _install_reasoning_provider(monkeypatch, provider)
    await harness.panel.get_by_label("Task instruction").fill("Continue to role details.")
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)

    worker = next(
        item for item in harness.panel.context.service_workers if "/background.js" in item.url
    )
    try:
        await worker.evaluate("() => chrome.runtime.reload()")
    except Exception:
        # Reload destroys the evaluating worker's execution context by design.
        pass

    await asyncio.wait_for(provider.cancelled.wait(), timeout=15)
    await asyncio.wait_for(harness.service.wait_for_attached_browser(), timeout=15)
    await expect(harness.demo.get_by_role("heading", name="1. Contact details")).to_be_visible()
    assert not harness.demo.is_closed(), "extension reload must leave the user tab open"
    assert harness.service.runtime_session is None


async def test_mode_c_runtime_restart_requires_fresh_attachment_without_replay(
    attached_harness: AttachedHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = attached_harness
    provider = ScriptedReasoner(
        target_name="Continue to role details",
        evidence="2. Role details",
        blocked=True,
    )
    _install_reasoning_provider(monkeypatch, provider)
    await harness.panel.get_by_label("Task instruction").fill("Continue to role details.")
    await harness.panel.get_by_role("button", name="Send task").click()
    await asyncio.wait_for(provider.deciding.wait(), timeout=15)

    old_service = harness.service
    await old_service.close()
    await asyncio.wait_for(provider.cancelled.wait(), timeout=15)
    await expect(harness.demo.get_by_role("heading", name="1. Contact details")).to_be_visible()
    assert not harness.demo.is_closed()

    replacement = ExtensionBridgeService(
        old_service.socket_path,
        config_path=harness.config_path,
        database_path=old_service.database_path,
        credential_store=harness.credentials,
    )
    try:
        await replacement.start()
        await expect(
            harness.panel.get_by_role("button", name="Connect runtime host")
        ).to_be_visible(timeout=15_000)
        await harness.panel.get_by_role("button", name="Connect runtime host").click()
        await expect(harness.panel.get_by_role("button", name="Disconnect host")).to_be_visible(
            timeout=15_000
        )
        await harness.panel.get_by_role("button", name="Capture active tab").click()
        await expect(harness.panel.get_by_role("button", name="Confirm and attach")).to_be_visible()
        await harness.panel.get_by_role("button", name="Confirm and attach").click()

        browser = await asyncio.wait_for(
            replacement.wait_for_attached_browser(wait_seconds=15),
            timeout=15,
        )
        assert browser is not None
        assert replacement.runtime_session is not None
        assert replacement.runtime_session["status"] == "idle"
        assert (await browser.observe()).title == "BROWSKI local application demo"
        await expect(harness.demo.get_by_role("heading", name="1. Contact details")).to_be_visible()
    finally:
        await replacement.close()
